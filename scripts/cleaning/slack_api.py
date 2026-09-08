from __future__ import annotations

import time
from typing import Any, Dict, Iterable, Optional

import requests


class SlackAPIError(RuntimeError):
    """Raised when Slack returns an HTTP or Web API error."""


class SlackClient:
    def __init__(self, token: str, *, timeout: int = 30, max_attempts: int = 3) -> None:
        if not token:
            raise ValueError("Slack token is required.")
        self.token = token
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.base_url = "https://slack.com/api"
        self.headers = {"Authorization": f"Bearer {token}"}
        self._workspace_users: Optional[list[Dict[str, Any]]] = None

    def _api_call(
        self,
        method: str,
        *,
        http_method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/{method}"
        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                response = requests.request(
                    http_method,
                    url,
                    headers={**self.headers, "Content-Type": "application/json"},
                    params=params,
                    json=json_body,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    raise SlackAPIError(f"Slack request failed for {method}: {exc}") from exc
                time.sleep(attempt)
                continue

            if response.status_code == 429:
                if attempt == self.max_attempts:
                    raise SlackAPIError(
                        f"Slack rate limited {method} after {self.max_attempts} attempts."
                    )
                retry_after = response.headers.get("Retry-After", "1")
                try:
                    wait_seconds = max(1, int(retry_after))
                except ValueError:
                    wait_seconds = 1
                time.sleep(wait_seconds)
                continue

            if response.status_code >= 500:
                if attempt == self.max_attempts:
                    raise SlackAPIError(
                        f"Slack returned HTTP {response.status_code} for {method}: {response.text}"
                    )
                time.sleep(attempt)
                continue

            if not response.ok:
                raise SlackAPIError(
                    f"Slack returned HTTP {response.status_code} for {method}: {response.text}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise SlackAPIError(
                    f"Slack returned a non-JSON response for {method}: {response.text[:500]}"
                ) from exc

            if not payload.get("ok"):
                detail = payload.get("error", "unknown_error")
                needed = payload.get("needed")
                provided = payload.get("provided")
                scope_detail = ""
                if needed:
                    scope_detail = f" needed={needed!r} provided={provided!r}"
                raise SlackAPIError(f"Slack API error for {method}: {detail}.{scope_detail}")

            return payload

        if last_error:
            raise SlackAPIError(f"Slack request failed for {method}: {last_error}")
        raise SlackAPIError(f"Slack request failed for {method}.")


    def list_users(self, *, max_pages: int = 50) -> list[Dict[str, Any]]:
        if self._workspace_users is not None:
            return list(self._workspace_users)

        members: list[Dict[str, Any]] = []
        cursor = ""
        for _ in range(max_pages):
            params: Dict[str, Any] = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            payload = self._api_call("users.list", params=params)
            members.extend(payload.get("members", []))
            cursor = str((payload.get("response_metadata") or {}).get("next_cursor") or "")
            if not cursor:
                self._workspace_users = members
                return list(members)

        raise SlackAPIError(
            f"Slack users.list exceeded {max_pages} pages while resolving a Canvas mention."
        )

    @staticmethod
    def _normalize_person_name(value: str) -> str:
        return " ".join(str(value or "").strip().lstrip("@").split()).casefold()

    def resolve_user_id(self, display_name: str) -> Optional[str]:
        wanted = self._normalize_person_name(display_name)
        if not wanted:
            return None

        matches: list[Dict[str, Any]] = []
        for member in self.list_users():
            if member.get("deleted") or member.get("is_bot"):
                continue
            profile = member.get("profile") or {}
            names = {
                self._normalize_person_name(member.get("name") or ""),
                self._normalize_person_name(member.get("real_name") or ""),
                self._normalize_person_name(profile.get("display_name") or ""),
                self._normalize_person_name(profile.get("real_name") or ""),
            }
            names.discard("")
            if wanted in names:
                matches.append(member)

        if len(matches) == 1:
            return str(matches[0].get("id") or "") or None
        if len(matches) > 1:
            ids = ", ".join(str(item.get("id") or "") for item in matches)
            raise SlackAPIError(
                f"Canvas name {display_name!r} matches multiple Slack users ({ids}). "
                "Use a Slack mention that preserves the user ID or make the display name unique."
            )
        return None

    def conversations_info(self, channel: str) -> Dict[str, Any]:
        return self._api_call("conversations.info", params={"channel": channel})["channel"]

    def files_info(self, file_id: str) -> Dict[str, Any]:
        return self._api_call("files.info", params={"file": file_id})["file"]

    def list_canvases(self, channel: str) -> list[Dict[str, Any]]:
        payload = self._api_call(
            "files.list",
            params={"channel": channel, "types": "canvas", "count": 100},
        )
        return list(payload.get("files", []))

    def resolve_channel_canvas_id(
        self,
        channel: str,
        *,
        explicit_canvas_id: str = "",
        canvas_title: str = "",
    ) -> str:
        if explicit_canvas_id:
            return explicit_canvas_id

        channel_info = self.conversations_info(channel)
        properties = channel_info.get("properties") or {}
        canvas = properties.get("canvas")
        if isinstance(canvas, str) and canvas:
            return canvas
        if isinstance(canvas, dict):
            for key in ("id", "canvas_id", "file_id"):
                if canvas.get(key):
                    return str(canvas[key])

        canvases = self.list_canvases(channel)
        if canvas_title:
            wanted = canvas_title.casefold()
            title_matches = [
                item for item in canvases
                if wanted in str(item.get("title") or item.get("name") or "").casefold()
            ]
            if len(title_matches) == 1:
                return str(title_matches[0]["id"])
            if len(title_matches) > 1:
                raise SlackAPIError(
                    f"More than one Canvas matched title {canvas_title!r}. Set SLACK_CLEANING_CANVAS_ID explicitly."
                )

        if len(canvases) == 1:
            return str(canvases[0]["id"])
        if not canvases:
            raise SlackAPIError(
                "No Canvas was found for the cleaning channel. Set SLACK_CLEANING_CANVAS_ID explicitly."
            )
        raise SlackAPIError(
            "Multiple Canvases are visible in the channel. Set SLACK_CLEANING_CANVAS_ID explicitly."
        )

    def download_canvas(self, canvas_id: str) -> str:
        file_info = self.files_info(canvas_id)
        download_url = file_info.get("url_private_download") or file_info.get("url_private")
        if not download_url:
            raise SlackAPIError(
                f"Slack did not provide a private download URL for Canvas {canvas_id}."
            )

        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = requests.get(
                    download_url,
                    headers=self.headers,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    raise SlackAPIError(f"Could not download Canvas {canvas_id}: {exc}") from exc
                time.sleep(attempt)
                continue

            if response.status_code == 429:
                if attempt == self.max_attempts:
                    raise SlackAPIError(f"Slack rate limited Canvas download {canvas_id}.")
                retry_after = response.headers.get("Retry-After", "1")
                try:
                    wait_seconds = max(1, int(retry_after))
                except ValueError:
                    wait_seconds = 1
                time.sleep(wait_seconds)
                continue

            if response.status_code >= 500:
                if attempt == self.max_attempts:
                    raise SlackAPIError(
                        f"Slack returned HTTP {response.status_code} while downloading Canvas {canvas_id}."
                    )
                time.sleep(attempt)
                continue

            if not response.ok:
                raise SlackAPIError(
                    f"Slack returned HTTP {response.status_code} while downloading Canvas {canvas_id}: {response.text[:500]}"
                )

            if not response.encoding:
                response.encoding = "utf-8"
            return response.text

        if last_error:
            raise SlackAPIError(f"Could not download Canvas {canvas_id}: {last_error}")
        raise SlackAPIError(f"Could not download Canvas {canvas_id}.")

    def conversation_history(
        self,
        channel: str,
        *,
        oldest: Optional[str] = None,
        max_pages: int = 20,
    ) -> list[Dict[str, Any]]:
        messages: list[Dict[str, Any]] = []
        cursor = ""

        for _ in range(max_pages):
            params: Dict[str, Any] = {
                "channel": channel,
                "limit": 100,
                "include_all_metadata": True,
            }
            if oldest:
                params["oldest"] = oldest
            if cursor:
                params["cursor"] = cursor

            payload = self._api_call("conversations.history", params=params)
            messages.extend(payload.get("messages", []))
            cursor = str((payload.get("response_metadata") or {}).get("next_cursor") or "")
            if not cursor:
                break
        else:
            raise SlackAPIError(
                f"Channel history exceeded {max_pages} pages. Increase CLEANING_MAX_HISTORY_PAGES."
            )

        return messages

    def thread_replies(self, channel: str, thread_ts: str) -> list[Dict[str, Any]]:
        messages: list[Dict[str, Any]] = []
        cursor = ""

        while True:
            params: Dict[str, Any] = {
                "channel": channel,
                "ts": thread_ts,
                "limit": 100,
                "include_all_metadata": True,
            }
            if cursor:
                params["cursor"] = cursor

            payload = self._api_call("conversations.replies", params=params)
            messages.extend(payload.get("messages", []))
            cursor = str((payload.get("response_metadata") or {}).get("next_cursor") or "")
            if not cursor:
                return messages

    def post_message(
        self,
        channel: str,
        text: str,
        *,
        thread_ts: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"channel": channel, "text": text}
        if thread_ts:
            body["thread_ts"] = thread_ts
        if metadata:
            body["metadata"] = metadata
        return self._api_call("chat.postMessage", http_method="POST", json_body=body)

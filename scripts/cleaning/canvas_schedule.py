from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
import re
from typing import Iterable, Optional

DATE_RE = re.compile(r"(?<!\d)(?P<day>\d{1,2})\.(?P<month>\d{1,2})(?!\d)")
YEAR_RE = re.compile(r"\b(20\d{2})\b")
USER_ID_RE = re.compile(r"\bU[A-Z0-9]{8,}\b")
PROFILE_URL_RE = re.compile(r"https?://[^\s\"'<>]*\.slack\.com/team/(U[A-Z0-9]+)", re.I)
CANVAS_MENTION_RE = re.compile(r"!\[\]\(@(U[A-Z0-9]+)\)")
MESSAGE_MENTION_RE = re.compile(r"<@(U[A-Z0-9]+)>")
BIG_CLEANING_RE = re.compile(r"\bbig\s+cell\s+culture\s+cleaning\b", re.I)


class CanvasScheduleError(ValueError):
    """Raised when Canvas schedule content cannot be interpreted safely."""


@dataclass(frozen=True)
class CleaningEntry:
    scheduled_date: date
    kind: str
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    note: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        return (
            self.scheduled_date.isoformat(),
            self.kind,
            self.user_id or self.user_name or "",
        )


class _CanvasHTMLTextExtractor(HTMLParser):
    """Turn Canvas export HTML into text while preserving Slack user IDs."""

    BLOCK_TAGS = {
        "address", "article", "aside", "blockquote", "br", "div", "footer",
        "h1", "h2", "h3", "h4", "header", "hr", "li", "main", "p",
        "section", "table", "td", "th", "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._href_stack: list[Optional[str]] = []

    def _newline(self) -> None:
        if self.parts and self.parts[-1] != "\n":
            self.parts.append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag in self.BLOCK_TAGS:
            self._newline()

        attr_map = {key.lower(): value for key, value in attrs}
        href = attr_map.get("href")
        if tag == "a":
            self._href_stack.append(href)

        for key, value in attrs:
            if not value:
                continue
            profile_match = PROFILE_URL_RE.search(value)
            if profile_match:
                self.parts.append(f" [SLACK_USER:{profile_match.group(1)}] ")
                break
            if key.lower() in {"data-user-id", "data-member-id", "data-entity-id"}:
                user_match = USER_ID_RE.search(value)
                if user_match:
                    self.parts.append(f" [SLACK_USER:{user_match.group(0)}] ")
                    break

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a" and self._href_stack:
            href = self._href_stack.pop()
            if href:
                profile_match = PROFILE_URL_RE.search(href)
                if profile_match:
                    self.parts.append(f" [SLACK_USER:{profile_match.group(1)}] ")
        if tag in self.BLOCK_TAGS:
            self._newline()

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def _looks_like_html(content: str) -> bool:
    sample = content[:2000].lower()
    return "<html" in sample or "<body" in sample or "</div>" in sample or "</p>" in sample


def normalize_canvas_content(content: str) -> str:
    if not isinstance(content, str) or not content.strip():
        raise CanvasScheduleError("The Slack Canvas is empty or could not be downloaded as text.")

    if _looks_like_html(content):
        parser = _CanvasHTMLTextExtractor()
        parser.feed(content)
        content = parser.text()

    content = PROFILE_URL_RE.sub(lambda m: f" [SLACK_USER:{m.group(1)}] ", content)
    content = CANVAS_MENTION_RE.sub(lambda m: f" [SLACK_USER:{m.group(1)}] ", content)
    content = MESSAGE_MENTION_RE.sub(lambda m: f" [SLACK_USER:{m.group(1)}] ", content)
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    content = re.sub(r"[ \t]+", " ", content)
    content = re.sub(r"\n[ \t]+", "\n", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()


def infer_schedule_year(content: str, fallback_year: int) -> int:
    years = [int(value) for value in YEAR_RE.findall(content)]
    plausible = [year for year in years if 2020 <= year <= 2100]
    if plausible:
        return plausible[0]
    return fallback_year


def _extract_user_id(chunk: str) -> Optional[str]:
    marker = re.search(r"\[SLACK_USER:(U[A-Z0-9]+)\]", chunk)
    if marker:
        return marker.group(1)

    profile = PROFILE_URL_RE.search(chunk)
    if profile:
        return profile.group(1)

    mention = CANVAS_MENTION_RE.search(chunk) or MESSAGE_MENTION_RE.search(chunk)
    if mention:
        return mention.group(1)

    return None


def _extract_user_name(chunk: str) -> Optional[str]:
    # Canvas HTML downloads do not always preserve the underlying Slack user ID.
    # Keep the visible mention as a fallback and resolve it with users.list later.
    markdown = re.search(r"\[@(?P<name>[^\]\n]+)\]\(", chunk)
    if markdown:
        name = markdown.group("name").strip()
        if name:
            return name

    visible = re.search(r"@(?P<name>[^\n\r<>{}\[\]()`*_]+)", chunk)
    if visible:
        name = visible.group("name").strip(" .,:;-\t")
        if name:
            return name

    # Some Canvas HTML exports render a user chip as plain display text without
    # the @ sign. In this schedule each date owns the text until the next date,
    # so a short non-empty first line is a safe display-name candidate.
    candidate = DATE_RE.sub("", chunk, count=1)
    candidate = re.sub(r"\[SLACK_USER:U[A-Z0-9]+\]", "", candidate)
    candidate = re.sub(r"https?://\S+", "", candidate)
    candidate = re.sub(r"[\[\]()*_`]+", " ", candidate)
    for line in candidate.splitlines():
        name = re.sub(r"\s+", " ", line).strip(" .,:;-\t")
        if not name or BIG_CLEANING_RE.search(name):
            continue
        if len(name) <= 80:
            return name.lstrip("@").strip() or None
    return None


def _clean_note(chunk: str) -> str:
    chunk = re.sub(r"\[SLACK_USER:U[A-Z0-9]+\]", "", chunk)
    chunk = re.sub(r"https?://\S+", "", chunk)
    chunk = re.sub(r"\s+", " ", chunk)
    return chunk.strip(" -|\t\n")


def parse_cleaning_schedule(
    content: str,
    *,
    fallback_year: int,
    schedule_year: Optional[int] = None,
) -> list[CleaningEntry]:
    normalized = normalize_canvas_content(content)
    year = schedule_year or infer_schedule_year(normalized, fallback_year)

    matches = list(DATE_RE.finditer(normalized))
    if not matches:
        raise CanvasScheduleError(
            "No cleaning dates were found. Expected dates such as '11.09'."
        )

    entries: list[CleaningEntry] = []
    seen: set[tuple[str, str, str]] = set()

    for index, match in enumerate(matches):
        chunk_end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        chunk = normalized[match.start():chunk_end]
        day = int(match.group("day"))
        month = int(match.group("month"))

        try:
            scheduled_date = date(year, month, day)
        except ValueError as exc:
            raise CanvasScheduleError(
                f"Invalid cleaning date '{match.group(0)}' for year {year}."
            ) from exc

        user_id = _extract_user_id(chunk)
        user_name = _extract_user_name(chunk)
        note = _clean_note(chunk)
        is_big = bool(BIG_CLEANING_RE.search(chunk))

        if is_big:
            entry = CleaningEntry(
                scheduled_date=scheduled_date,
                kind="big_cleaning",
                user_id=user_id,
                user_name=user_name,
                note=note,
            )
        elif user_id:
            entry = CleaningEntry(
                scheduled_date=scheduled_date,
                kind="individual",
                user_id=user_id,
                user_name=user_name,
                note=note,
            )
        elif user_name:
            entry = CleaningEntry(
                scheduled_date=scheduled_date,
                kind="individual",
                user_id=None,
                user_name=user_name,
                note=note,
            )
        else:
            entry = CleaningEntry(
                scheduled_date=scheduled_date,
                kind="unassigned",
                user_id=None,
                note=note,
            )

        if entry.key not in seen:
            seen.add(entry.key)
            entries.append(entry)

    entries.sort(key=lambda item: (item.scheduled_date, item.kind, item.user_id or ""))
    return entries


def entries_on(entries: Iterable[CleaningEntry], target: date) -> list[CleaningEntry]:
    return [entry for entry in entries if entry.scheduled_date == target]

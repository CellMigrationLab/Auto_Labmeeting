from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date, datetime, time
import os
from typing import Any, Dict, Iterable, Optional
from zoneinfo import ZoneInfo

from canvas_schedule import CleaningEntry, parse_cleaning_schedule
from slack_api import SlackClient

ASSIGNMENT_EVENT = "lab_cleaning_assignment"
REMINDER_EVENT = "lab_cleaning_reminder"
BIG_CLEANING_EVENT = "lab_cleaning_big_cleaning"


def build_assignment_message(entry: CleaningEntry) -> str:
    return (
        f"<@{entry.user_id}> it is your turn for cell culture cleaning today "
        ":scientist::broom::sponge:.\n"
        "Please reply in this thread once the cleaning is complete. Thank you!"
    )


def build_reminder_message(entry: CleaningEntry) -> str:
    return (
        f"<@{entry.user_id}> friendly reminder: please complete the cell culture "
        "cleaning and reply in this thread when finished. :broom:"
    )


def build_big_cleaning_message(entry: CleaningEntry) -> str:
    note = entry.note or "Big cell culture cleaning"
    date_label = entry.scheduled_date.strftime("%d.%m")
    return (
        f":scientist::broom::sponge: *{note}* ({date_label})\n"
        "This is a channel-wide cleaning day. Please coordinate the cleaning here."
    )


def _metadata(event_type: str, **payload: str) -> Dict[str, Any]:
    context = {
        "automation": "lab_cleaning",
        "event_type": event_type,
        **{key: str(value) for key, value in payload.items()},
    }
    category = "reminder" if event_type == REMINDER_EVENT else "status_update"
    return {
        "event_type": "notification",
        "event_payload": {
            "notification_type": "info",
            "title": "Lab cleaning automation",
            "category": category,
            "context": context,
        },
    }


def _message_metadata(message: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    metadata = message.get("metadata") or {}
    metadata_type = str(metadata.get("event_type") or "")
    payload = dict(metadata.get("event_payload") or {})
    if metadata_type == "notification":
        context = dict(payload.get("context") or {})
        if context.get("automation") == "lab_cleaning":
            return str(context.get("event_type") or ""), context
    return metadata_type, payload


def find_matching_messages(
    messages: Iterable[Dict[str, Any]],
    *,
    event_type: str,
    schedule_date: str,
    assigned_user: str = "",
) -> list[Dict[str, Any]]:
    matches: list[Dict[str, Any]] = []
    for message in messages:
        current_type, payload = _message_metadata(message)
        if current_type != event_type:
            continue
        if str(payload.get("schedule_date") or "") != schedule_date:
            continue
        if assigned_user and str(payload.get("assigned_user") or "") != assigned_user:
            continue
        matches.append(message)
    return matches


def assigned_user_replied(replies: Iterable[Dict[str, Any]], user_id: str) -> bool:
    return any(
        str(message.get("user") or "") == user_id
        and not message.get("bot_id")
        and not message.get("subtype") in {"message_deleted"}
        for message in replies
    )


def reminder_sent_on(
    replies: Iterable[Dict[str, Any]],
    *,
    schedule_date: str,
    assigned_user: str,
    reminder_date: str,
) -> bool:
    for message in replies:
        event_type, payload = _message_metadata(message)
        if event_type != REMINDER_EVENT:
            continue
        if str(payload.get("schedule_date") or "") != schedule_date:
            continue
        if str(payload.get("assigned_user") or "") != assigned_user:
            continue
        if str(payload.get("reminder_date") or "") == reminder_date:
            return True
    return False


def _message_from_post_response(response: Dict[str, Any], metadata: Dict[str, Any]) -> Dict[str, Any]:
    message = dict(response.get("message") or {})
    if response.get("ts") and not message.get("ts"):
        message["ts"] = response["ts"]
    message.setdefault("metadata", metadata)
    return message


def resolve_canvas_user_ids(
    client: SlackClient,
    entries: list[CleaningEntry],
) -> list[CleaningEntry]:
    resolved_entries: list[CleaningEntry] = []
    for entry in entries:
        if entry.kind != "individual" or entry.user_id:
            resolved_entries.append(entry)
            continue

        if not entry.user_name:
            resolved_entries.append(replace(entry, kind="unassigned"))
            continue

        resolved_user_id = client.resolve_user_id(entry.user_name)
        if resolved_user_id:
            print(
                f"Resolved Canvas user {entry.user_name!r} to Slack user {resolved_user_id} "
                f"for {entry.scheduled_date.isoformat()}."
            )
            resolved_entries.append(replace(entry, user_id=resolved_user_id))
        else:
            print(
                f"Could not resolve Canvas user {entry.user_name!r} in the Slack workspace "
                f"for {entry.scheduled_date.isoformat()}."
            )
            resolved_entries.append(replace(entry, kind="unassigned"))

    return resolved_entries


def _oldest_timestamp(entries: list[CleaningEntry], timezone_name: str, today: date) -> Optional[str]:
    relevant_dates = [entry.scheduled_date for entry in entries if entry.scheduled_date <= today]
    if not relevant_dates:
        return None
    zone = ZoneInfo(timezone_name)
    oldest = datetime.combine(min(relevant_dates), time.min, tzinfo=zone)
    return str(oldest.timestamp())


def run_daily(
    client: SlackClient,
    *,
    channel: str,
    canvas_content: str,
    canvas_id: str,
    today: date,
    timezone_name: str,
    schedule_year: Optional[int] = None,
    max_history_pages: int = 20,
) -> Dict[str, int]:
    entries = parse_cleaning_schedule(
        canvas_content,
        fallback_year=today.year,
        schedule_year=schedule_year,
    )
    entries = resolve_canvas_user_ids(client, entries)

    stats = {
        "assignments_sent": 0,
        "big_cleaning_announcements_sent": 0,
        "completed": 0,
        "reminders_sent": 0,
        "unassigned_today": 0,
    }

    oldest = _oldest_timestamp(entries, timezone_name, today)
    history = (
        client.conversation_history(channel, oldest=oldest, max_pages=max_history_pages)
        if oldest
        else []
    )

    today_iso = today.isoformat()

    for entry in entries:
        if entry.scheduled_date != today:
            continue

        schedule_date = entry.scheduled_date.isoformat()

        if entry.kind == "unassigned":
            stats["unassigned_today"] += 1
            print(f"No Slack user is assigned for {schedule_date}; nothing was sent.")
            continue

        if entry.kind == "big_cleaning":
            existing = find_matching_messages(
                history,
                event_type=BIG_CLEANING_EVENT,
                schedule_date=schedule_date,
            )
            if existing:
                print(f"Big cleaning announcement already exists for {schedule_date}.")
                continue

            metadata = _metadata(
                BIG_CLEANING_EVENT,
                schedule_date=schedule_date,
                source_canvas_id=canvas_id,
            )
            response = client.post_message(
                channel,
                build_big_cleaning_message(entry),
                metadata=metadata,
            )
            history.append(_message_from_post_response(response, metadata))
            stats["big_cleaning_announcements_sent"] += 1
            print(f"Sent big cleaning announcement for {schedule_date}.")
            continue

        existing = find_matching_messages(
            history,
            event_type=ASSIGNMENT_EVENT,
            schedule_date=schedule_date,
            assigned_user=entry.user_id or "",
        )
        if existing:
            print(f"Cleaning assignment already exists for {schedule_date} and {entry.user_id}.")
            continue

        metadata = _metadata(
            ASSIGNMENT_EVENT,
            schedule_date=schedule_date,
            assigned_user=entry.user_id or "",
            source_canvas_id=canvas_id,
        )
        response = client.post_message(
            channel,
            build_assignment_message(entry),
            metadata=metadata,
        )
        history.append(_message_from_post_response(response, metadata))
        stats["assignments_sent"] += 1
        print(f"Sent cleaning assignment for {schedule_date} to {entry.user_id}.")

    for entry in entries:
        if entry.kind != "individual" or entry.scheduled_date >= today:
            continue

        schedule_date = entry.scheduled_date.isoformat()
        assignment_messages = find_matching_messages(
            history,
            event_type=ASSIGNMENT_EVENT,
            schedule_date=schedule_date,
            assigned_user=entry.user_id or "",
        )
        if not assignment_messages:
            print(
                f"No original cleaning message exists for {schedule_date} and {entry.user_id}; "
                "not sending a late reminder."
            )
            continue

        all_replies: list[Dict[str, Any]] = []
        threads: list[tuple[Dict[str, Any], list[Dict[str, Any]]]] = []
        for assignment_message in assignment_messages:
            thread_ts = str(assignment_message.get("ts") or "")
            if not thread_ts:
                continue
            replies = client.thread_replies(channel, thread_ts)
            threads.append((assignment_message, replies))
            all_replies.extend(replies)

        if assigned_user_replied(all_replies, entry.user_id or ""):
            stats["completed"] += 1
            print(f"{entry.user_id} has replied to the {schedule_date} cleaning thread.")
            continue

        if reminder_sent_on(
            all_replies,
            schedule_date=schedule_date,
            assigned_user=entry.user_id or "",
            reminder_date=today_iso,
        ):
            print(f"A reminder was already sent today for {schedule_date} and {entry.user_id}.")
            continue

        valid_threads = [item for item in threads if item[0].get("ts")]
        if not valid_threads:
            print(f"Could not find a valid Slack thread timestamp for {schedule_date}.")
            continue

        parent, _ = min(valid_threads, key=lambda item: float(item[0]["ts"]))
        thread_ts = str(parent["ts"])
        metadata = _metadata(
            REMINDER_EVENT,
            schedule_date=schedule_date,
            assigned_user=entry.user_id or "",
            reminder_date=today_iso,
            parent_ts=thread_ts,
            source_canvas_id=canvas_id,
        )
        client.post_message(
            channel,
            build_reminder_message(entry),
            thread_ts=thread_ts,
            metadata=metadata,
        )
        stats["reminders_sent"] += 1
        print(f"Sent reminder for {schedule_date} to {entry.user_id}.")

    return stats


def _parse_optional_year(value: str) -> Optional[int]:
    if not value:
        return None
    year = int(value)
    if year < 2020 or year > 2100:
        raise argparse.ArgumentTypeError("Schedule year must be between 2020 and 2100.")
    return year


def _parse_date_override(value: str) -> date:
    return date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read the lab cleaning rota from a Slack Canvas and manage Slack reminders."
    )
    parser.add_argument('--token', default=os.getenv('SLACK_TOKEN', ''), help='Slack bot token')
    parser.add_argument('--channel', default=os.getenv('SLACK_CLEANING_CHANNEL', ''), help='Slack channel ID')
    parser.add_argument('--canvas-id', default=os.getenv('SLACK_CLEANING_CANVAS_ID', ''), help='Optional Canvas file ID')
    parser.add_argument('--canvas-title', default=os.getenv('SLACK_CLEANING_CANVAS_TITLE', 'Cleaning schedule'), help='Canvas title hint')
    parser.add_argument('--timezone', default=os.getenv('CLEANING_TIMEZONE', 'Europe/Helsinki'), help='IANA timezone')
    parser.add_argument('--schedule-year', default=os.getenv('CLEANING_SCHEDULE_YEAR', ''), help='Override year for DD.MM entries')
    parser.add_argument('--date', default='', help='Override today for a manual test, YYYY-MM-DD')
    parser.add_argument('--max-history-pages', type=int, default=int(os.getenv('CLEANING_MAX_HISTORY_PAGES', '20')))
    args = parser.parse_args()

    if not args.token:
        parser.error('Slack token is required through --token or SLACK_TOKEN.')
    if not args.channel:
        parser.error('Slack cleaning channel is required through --channel or SLACK_CLEANING_CHANNEL.')

    schedule_year = _parse_optional_year(str(args.schedule_year))
    if args.date:
        today = _parse_date_override(args.date)
    else:
        today = datetime.now(ZoneInfo(args.timezone)).date()

    client = SlackClient(args.token)
    canvas_id = client.resolve_channel_canvas_id(
        args.channel,
        explicit_canvas_id=args.canvas_id,
        canvas_title=args.canvas_title,
    )
    print(f"Using Slack Canvas {canvas_id}.")
    canvas_content = client.download_canvas(canvas_id)

    stats = run_daily(
        client,
        channel=args.channel,
        canvas_content=canvas_content,
        canvas_id=canvas_id,
        today=today,
        timezone_name=args.timezone,
        schedule_year=schedule_year,
        max_history_pages=args.max_history_pages,
    )
    print(f"Cleaning workflow summary: {stats}")


if __name__ == '__main__':
    main()

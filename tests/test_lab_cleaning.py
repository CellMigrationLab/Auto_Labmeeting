import sys
from datetime import date
from pathlib import Path
import unittest

CLEANING_DIR = Path(__file__).resolve().parents[1] / "scripts" / "cleaning"
sys.path.insert(0, str(CLEANING_DIR))

from canvas_schedule import CanvasScheduleError, parse_cleaning_schedule
from lab_cleaning import (
    ASSIGNMENT_EVENT,
    BIG_CLEANING_EVENT,
    REMINDER_EVENT,
    assigned_user_replied,
    find_matching_messages,
    reminder_sent_on,
    run_daily,
)


class FakeSlackClient:
    def __init__(self, history=None, threads=None, users=None):
        self.history = list(history or [])
        self.threads = {key: list(value) for key, value in (threads or {}).items()}
        self.posted = []
        self.counter = 1000
        self.users = dict(users or {})

    def resolve_user_id(self, display_name):
        return self.users.get(display_name)

    def conversation_history(self, channel, oldest=None, max_pages=20):
        return list(self.history)

    def thread_replies(self, channel, thread_ts):
        return list(self.threads.get(thread_ts, []))

    def post_message(self, channel, text, thread_ts="", metadata=None):
        self.counter += 1
        ts = f"{self.counter}.000001"
        message = {
            "ts": ts,
            "text": text,
            "metadata": metadata or {},
            "user": "UBOT000000",
            "bot_id": "BBOT000000",
        }
        self.posted.append({
            "channel": channel,
            "text": text,
            "thread_ts": thread_ts,
            "metadata": metadata or {},
            "ts": ts,
        })
        if thread_ts:
            self.threads.setdefault(thread_ts, []).append(message)
        else:
            self.history.append(message)
            self.threads.setdefault(ts, [message])
        return {"ok": True, "ts": ts, "message": message}


def metadata(event_type, **payload):
    return {
        "event_type": "notification",
        "event_payload": {
            "notification_type": "info",
            "title": "Lab cleaning automation",
            "category": "reminder" if event_type == REMINDER_EVENT else "status_update",
            "context": {
                "automation": "lab_cleaning",
                "event_type": event_type,
                **payload,
            },
        },
    }


class CanvasParserTests(unittest.TestCase):
    def test_parses_current_style_markdown(self):
        content = """
Cleaning schedule - 2026
11.09 [@Example](https://example.slack.com/team/U0123456789)
18.09 [@Other](https://example.slack.com/team/U0234567890)
25.09
02.10 **Big cell culture cleaning**
18.12 **Big cell culture cleaning + Incubator sterilizations**
"""
        entries = parse_cleaning_schedule(content, fallback_year=2025)
        self.assertEqual(5, len(entries))
        self.assertEqual(date(2026, 9, 11), entries[0].scheduled_date)
        self.assertEqual("individual", entries[0].kind)
        self.assertEqual("U0123456789", entries[0].user_id)
        self.assertEqual("unassigned", entries[2].kind)
        self.assertEqual("big_cleaning", entries[3].kind)
        self.assertIn("Incubator sterilizations", entries[4].note)

    def test_parses_html_profile_link(self):
        html = """
<html><body><h1>Cleaning schedule - 2026</h1>
<p>11.09 <a href="https://example.slack.com/team/U0123456789">@Example</a></p>
</body></html>
"""
        entries = parse_cleaning_schedule(html, fallback_year=2025)
        self.assertEqual("U0123456789", entries[0].user_id)
        self.assertEqual(date(2026, 9, 11), entries[0].scheduled_date)


    def test_parses_canvas_html_when_profile_url_is_stripped(self):
        html = """
<html><body><h1>Cleaning schedule - 2026</h1>
<p>28.08 <span class="mention">@Adan</span></p>
</body></html>
"""
        entries = parse_cleaning_schedule(html, fallback_year=2025)
        self.assertEqual("individual", entries[0].kind)
        self.assertIsNone(entries[0].user_id)
        self.assertEqual("Adan", entries[0].user_name)

    def test_parses_canvas_html_plain_display_name(self):
        html = """
<html><body><h1>Cleaning schedule - 2026</h1>
<p>28.08 <span>Adan</span></p>
</body></html>
"""
        entries = parse_cleaning_schedule(html, fallback_year=2025)
        self.assertEqual("individual", entries[0].kind)
        self.assertEqual("Adan", entries[0].user_name)

    def test_uses_fallback_year_when_heading_has_no_year(self):
        entries = parse_cleaning_schedule(
            "11.09 [@Example](https://example.slack.com/team/U0123456789)",
            fallback_year=2027,
        )
        self.assertEqual(2027, entries[0].scheduled_date.year)

    def test_schedule_year_override_wins(self):
        entries = parse_cleaning_schedule(
            "Cleaning schedule - 2026\n11.09 [@Example](https://example.slack.com/team/U0123456789)",
            fallback_year=2027,
            schedule_year=2028,
        )
        self.assertEqual(2028, entries[0].scheduled_date.year)

    def test_invalid_date_fails(self):
        with self.assertRaises(CanvasScheduleError):
            parse_cleaning_schedule("31.02 @Nobody", fallback_year=2026)


class StateHelperTests(unittest.TestCase):
    def test_finds_metadata_assignment(self):
        messages = [{
            "ts": "1.0",
            "metadata": metadata(
                ASSIGNMENT_EVENT,
                schedule_date="2026-09-11",
                assigned_user="U0123456789",
            ),
        }]
        matches = find_matching_messages(
            messages,
            event_type=ASSIGNMENT_EVENT,
            schedule_date="2026-09-11",
            assigned_user="U0123456789",
        )
        self.assertEqual(1, len(matches))

    def test_only_assigned_user_reply_completes(self):
        replies = [
            {"user": "U0999999999", "text": "done"},
            {"user": "U0123456789", "text": "done"},
        ]
        self.assertTrue(assigned_user_replied(replies, "U0123456789"))
        self.assertFalse(assigned_user_replied(replies, "U0888888888"))

    def test_detects_same_day_reminder_metadata(self):
        replies = [{
            "metadata": metadata(
                REMINDER_EVENT,
                schedule_date="2026-09-11",
                assigned_user="U0123456789",
                reminder_date="2026-09-12",
            )
        }]
        self.assertTrue(reminder_sent_on(
            replies,
            schedule_date="2026-09-11",
            assigned_user="U0123456789",
            reminder_date="2026-09-12",
        ))


class DailyWorkflowTests(unittest.TestCase):
    canvas = "Cleaning schedule - 2026\n11.09 [@Example](https://example.slack.com/team/U0123456789)"


    def test_visible_canvas_name_is_resolved_via_slack_directory(self):
        content = "Cleaning schedule - 2026\n28.08 @Adan"
        client = FakeSlackClient(users={"Adan": "U09G376BEDC"})
        stats = run_daily(
            client,
            channel="C123",
            canvas_content=content,
            canvas_id="F123",
            today=date(2026, 8, 28),
            timezone_name="Europe/Helsinki",
        )
        self.assertEqual(1, stats["assignments_sent"])
        self.assertEqual(0, stats["unassigned_today"])
        self.assertIn("<@U09G376BEDC>", client.posted[0]["text"])

    def test_unresolvable_visible_name_stays_unassigned(self):
        content = "Cleaning schedule - 2026\n28.08 @Unknown Person"
        client = FakeSlackClient(users={})
        stats = run_daily(
            client,
            channel="C123",
            canvas_content=content,
            canvas_id="F123",
            today=date(2026, 8, 28),
            timezone_name="Europe/Helsinki",
        )
        self.assertEqual(0, stats["assignments_sent"])
        self.assertEqual(1, stats["unassigned_today"])

    def test_initial_assignment_is_idempotent(self):
        client = FakeSlackClient()
        first = run_daily(
            client,
            channel="C123",
            canvas_content=self.canvas,
            canvas_id="F123",
            today=date(2026, 9, 11),
            timezone_name="Europe/Helsinki",
        )
        second = run_daily(
            client,
            channel="C123",
            canvas_content=self.canvas,
            canvas_id="F123",
            today=date(2026, 9, 11),
            timezone_name="Europe/Helsinki",
        )
        self.assertEqual(1, first["assignments_sent"])
        self.assertEqual(0, second["assignments_sent"])
        self.assertEqual(1, len(client.posted))

    def test_daily_reminder_is_idempotent(self):
        parent = {
            "ts": "100.000001",
            "metadata": metadata(
                ASSIGNMENT_EVENT,
                schedule_date="2026-09-11",
                assigned_user="U0123456789",
            ),
            "user": "UBOT000000",
            "bot_id": "BBOT000000",
        }
        client = FakeSlackClient(history=[parent], threads={"100.000001": [parent]})
        first = run_daily(
            client,
            channel="C123",
            canvas_content=self.canvas,
            canvas_id="F123",
            today=date(2026, 9, 12),
            timezone_name="Europe/Helsinki",
        )
        second = run_daily(
            client,
            channel="C123",
            canvas_content=self.canvas,
            canvas_id="F123",
            today=date(2026, 9, 12),
            timezone_name="Europe/Helsinki",
        )
        self.assertEqual(1, first["reminders_sent"])
        self.assertEqual(0, second["reminders_sent"])
        self.assertEqual(1, len(client.posted))
        self.assertEqual("100.000001", client.posted[0]["thread_ts"])

    def test_assigned_user_reply_stops_reminders(self):
        parent = {
            "ts": "100.000001",
            "metadata": metadata(
                ASSIGNMENT_EVENT,
                schedule_date="2026-09-11",
                assigned_user="U0123456789",
            ),
            "user": "UBOT000000",
            "bot_id": "BBOT000000",
        }
        reply = {"ts": "101.0", "user": "U0123456789", "text": "Done"}
        client = FakeSlackClient(history=[parent], threads={"100.000001": [parent, reply]})
        stats = run_daily(
            client,
            channel="C123",
            canvas_content=self.canvas,
            canvas_id="F123",
            today=date(2026, 9, 12),
            timezone_name="Europe/Helsinki",
        )
        self.assertEqual(1, stats["completed"])
        self.assertEqual(0, stats["reminders_sent"])
        self.assertEqual([], client.posted)

    def test_other_user_reply_does_not_stop_reminder(self):
        parent = {
            "ts": "100.000001",
            "metadata": metadata(
                ASSIGNMENT_EVENT,
                schedule_date="2026-09-11",
                assigned_user="U0123456789",
            ),
            "user": "UBOT000000",
            "bot_id": "BBOT000000",
        }
        reply = {"ts": "101.0", "user": "U0999999999", "text": "Done"}
        client = FakeSlackClient(history=[parent], threads={"100.000001": [parent, reply]})
        stats = run_daily(
            client,
            channel="C123",
            canvas_content=self.canvas,
            canvas_id="F123",
            today=date(2026, 9, 12),
            timezone_name="Europe/Helsinki",
        )
        self.assertEqual(1, stats["reminders_sent"])

    def test_big_cleaning_announced_once(self):
        content = "Cleaning schedule - 2026\n09.10 Big cell culture cleaning"
        client = FakeSlackClient()
        first = run_daily(
            client,
            channel="C123",
            canvas_content=content,
            canvas_id="F123",
            today=date(2026, 10, 9),
            timezone_name="Europe/Helsinki",
        )
        second = run_daily(
            client,
            channel="C123",
            canvas_content=content,
            canvas_id="F123",
            today=date(2026, 10, 9),
            timezone_name="Europe/Helsinki",
        )
        self.assertEqual(1, first["big_cleaning_announcements_sent"])
        self.assertEqual(0, second["big_cleaning_announcements_sent"])
        self.assertEqual(BIG_CLEANING_EVENT, client.posted[0]["metadata"]["event_payload"]["context"]["event_type"])

    def test_blank_date_is_ignored(self):
        content = "Cleaning schedule - 2026\n16.10"
        client = FakeSlackClient()
        stats = run_daily(
            client,
            channel="C123",
            canvas_content=content,
            canvas_id="F123",
            today=date(2026, 10, 16),
            timezone_name="Europe/Helsinki",
        )
        self.assertEqual(1, stats["unassigned_today"])
        self.assertEqual([], client.posted)


if __name__ == "__main__":
    unittest.main()

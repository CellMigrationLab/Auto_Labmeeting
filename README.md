# Auto_Labmeeting

This repository automates several Cell Migration Lab Slack workflows:

- Weekly lab-meeting slide creation, Google Drive upload, and Slack sharing.
- Weekly Slack reminders for updating the lab-meeting slides.
- Bi-weekly lunch messages.
- Daily lab-cleaning assignments and reminders driven by a Slack Canvas.

## Lab meeting schedule

Skipped lab meeting dates are configured in `config/labmeeting_schedule.json`.

- `anchor_date` defines the first date in the rotation.
- `group_rotation` defines the alternating order of presenter groups.
- `groups` defines the presenters for each group.
- `skipped_dates` defines cancelled dates and the Slack message for each cancellation.

Skipped dates do not advance the presenter rotation.

## Slack Canvas lab-cleaning workflow

The new cleaning workflow is implemented in:

- `.github/workflows/daily_lab_cleaning.yml`
- `scripts/cleaning/lab_cleaning.py`
- `scripts/cleaning/canvas_schedule.py`
- `scripts/cleaning/slack_api.py`

The Slack Canvas is the source of truth for cleaning dates and assigned people. The parser reads Slack profile links/mentions directly, so there is no separate user-ID spreadsheet.

Example Canvas content:

```text
Cleaning schedule - 2026

11.09 @Person
18.09 @Person
25.09 @Person
02.10 @Person
09.10 Big cell culture cleaning
16.10
```

On an assigned date, the bot posts a top-level message and asks the assigned person to reply in that thread when cleaning is complete. On each later daily run, the workflow checks the thread. Until the assigned person replies, it posts at most one reminder per day in that same thread.

Blank dates are ignored. `Big cell culture cleaning` dates create one channel-wide announcement and are not individually reply-tracked.

See [`docs/LAB_CLEANING_CANVAS_SETUP.md`](docs/LAB_CLEANING_CANVAS_SETUP.md) for Slack scopes, GitHub secrets/variables, Canvas formatting, and the recommended manual test procedure.

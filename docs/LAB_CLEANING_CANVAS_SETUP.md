# Lab cleaning automation - Slack Canvas setup

The cleaning automation is independent from the existing lab-meeting slide workflows.
It uses a Slack Canvas as the schedule and Slack messages/threads as the persistent state.
No Google Sheet or database is required.

## How it works

1. The daily GitHub Action finds the cleaning Canvas in the configured Slack channel.
2. It downloads the Canvas and parses entries written as `DD.MM` plus a Slack profile link/mention.
3. On an individual cleaning date it posts a message mentioning the assigned user.
4. The message uses Slack's built-in `notification` metadata schema; the metadata context identifies the cleaning date and assigned user.
5. On later daily runs, the action reads the original thread.
6. Any reply from the assigned Slack user completes that assignment.
7. Until that reply exists, the bot posts at most one reminder per day in the original thread.
8. Blank dates are ignored.
9. `Big cell culture cleaning` dates create one channel-wide announcement and are not reply-tracked.

## Recommended Canvas format

Add the year to the title or heading when possible:

```text
Cleaning schedule - 2026

11.09 @Person
18.09 @Person
25.09 @Person
02.10 @Person
09.10 Big cell culture cleaning
16.10
18.12 Big cell culture cleaning + Incubator sterilizations
```

The existing Slack profile links are ideal. For example:

```text
11.09 [@Person](https://your-workspace.slack.com/team/U0123456789)
```

The workflow extracts `U0123456789` directly from the link. No separate people/ID table is needed.
Slack Canvas user mentions such as `![](@U0123456789)` and normal Slack mentions such as `<@U0123456789>` are also supported.

Your current `DD.MM` Canvas format works without changes. If the Canvas has no year, the workflow assumes the current year in `CLEANING_TIMEZONE`.
For year-spanning schedules, put the year in the Canvas heading or set the GitHub variable `CLEANING_SCHEDULE_YEAR`.

## Slack app scopes

For a public cleaning channel, add these Bot Token Scopes to the existing Slack app:

- `chat:write` - send assignments and reminders.
- `channels:history` - read channel history and thread replies.
- `channels:read` - inspect the channel and discover its channel Canvas.
- `files:read` - retrieve the Canvas file and its private download URL.
- `metadata.message:read` - read the cleaning metadata back from channel history.

The workflow uses Slack's built-in `notification` metadata schema, so you do **not** need to register custom metadata event types in the Slack app manifest.

For a private channel, use the corresponding `groups:history` and `groups:read` scopes instead of the public-channel read/history scopes.

After changing scopes, reinstall/re-authorize the Slack app in the workspace. Make sure the bot is a member of the cleaning channel.

## GitHub configuration

### Required secrets

`SLACK_TOKEN`
: Existing Slack bot token (`xoxb-...`). The token must include the scopes above after reauthorization.

`SLACK_CLEANING_CHANNEL`
: Channel ID such as `C0123456789`. Use the channel ID, not `#channel-name`.

### Optional secret

`SLACK_CLEANING_CANVAS_ID`
: The Canvas file ID, typically beginning with `F`. This is the most deterministic option. If omitted, the script first checks the channel Canvas property and then falls back to `files.list?types=canvas`.

### Optional repository variables

`SLACK_CLEANING_CANVAS_TITLE`
: Title hint used only if Canvas discovery needs a fallback. Default: `Cleaning schedule`.

`CLEANING_TIMEZONE`
: IANA timezone used for the cleaning date. Default: `Europe/Helsinki`.

`CLEANING_SCHEDULE_YEAR`
: Optional four-digit year override for `DD.MM` Canvas entries. Leave unset when the Canvas heading already contains the year.

`CLEANING_MAX_HISTORY_PAGES`
: Safety limit while reading channel history. Default: `20` pages.

## Finding the channel and Canvas IDs

Channel ID:
1. Open the Slack channel.
2. Open channel details.
3. Copy the channel ID from the About/details area, or copy a channel link and take the `C...` identifier.

Canvas ID:
1. Open the channel Canvas.
2. Copy its Slack link.
3. The Canvas/file identifier generally begins with `F`.

You can omit `SLACK_CLEANING_CANVAS_ID` initially and let the workflow auto-discover the channel Canvas. If the workflow reports multiple matching Canvases, set the ID explicitly.

## First safe test

1. Put a test row in the Canvas for yourself on a date you will use for the manual run.
2. Make sure that row contains your real Slack mention/profile link.
3. Open GitHub -> Actions -> Daily Lab Cleaning Reminder -> Run workflow.
4. Enter the test date as `YYYY-MM-DD`.
5. Confirm one top-level assignment message appears.
6. Run the workflow again with the same date. It should not create a duplicate assignment.
7. Run it for the following date without replying. It should create one reminder in the original thread.
8. Run it again for that same following date. It should not duplicate the reminder.
9. Reply to the original thread as the assigned person.
10. Run it for another later date. No further reminder should be sent for that assignment.

## Important behavior

- A reply from another person does not complete the assignment.
- Any reply by the assigned Slack user counts as completion; the reply text is not interpreted.
- The workflow does not edit the Canvas.
- Past rows should remain in the Canvas until their cleaning task is completed, because the Canvas controls which assignments are evaluated.
- If an individual date was missed completely and no original assignment message exists, the workflow does not send a late reminder. This avoids surprising users with a retroactive assignment.
- Big cleaning entries are announcements only and do not require a reply.

## Canvas download note

Slack represents Canvases as file objects. The script uses `files.info` to obtain `url_private_download` (or `url_private`) and downloads it with the bot token. Slack Canvas downloads can be HTML, so the parser preserves Slack user IDs from links/attributes while extracting the visible schedule text.

# Auto_Labmeeting

This repository creates the weekly lab meeting slides, uploads them to Google Drive, and shares the link in Slack.

## Skipping specific lab meeting dates

Skipped lab meeting dates are configured in `config/labmeeting_schedule.json`.

### Rotation logic

- `anchor_date` defines the first date in the rotation.
- `group_rotation` defines the alternating order of presenter groups.
- `groups` defines the presenters for each group.
- `skipped_dates` defines dates that should not generate slides, plus the custom Slack message that should be sent instead.

Skipped dates do **not** advance the presenter rotation. This means the same group that would have presented during the skipped week will present in the next active meeting.

### Example

```json
{
  "anchor_date": "2026-01-05",
  "group_rotation": ["group_1", "group_2"],
  "groups": {
    "group_1": ["Sarah", "Christine"],
    "group_2": ["Iván", "Marcela"]
  },
  "skipped_dates": {
    "2026-04-06": {
      "message": "There will be no lab meeting on 2026-04-06 because of Easter Monday. The same presenters will move to the following week."
    }
  }
}
```

Update the `message` field for each skipped date to match the holiday or reason for the cancellation.

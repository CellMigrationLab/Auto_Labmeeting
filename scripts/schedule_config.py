from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import json
from typing import Any, Dict, List, Optional

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "labmeeting_schedule.json"


class ScheduleConfigurationError(ValueError):
    """Raised when the schedule configuration is invalid."""


def _parse_date(date_str: str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ScheduleConfigurationError(
            f"Invalid date '{date_str}'. Expected format: YYYY-MM-DD."
        ) from exc


def load_schedule_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

    if not path.exists():
        raise ScheduleConfigurationError(
            f"Schedule configuration file not found: {path}"
        )

    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    required_keys = {"anchor_date", "group_rotation", "groups", "skipped_dates"}
    missing = required_keys.difference(config)
    if missing:
        missing_keys = ", ".join(sorted(missing))
        raise ScheduleConfigurationError(
            f"Missing required schedule configuration keys: {missing_keys}"
        )

    if not config["group_rotation"]:
        raise ScheduleConfigurationError("'group_rotation' cannot be empty.")

    if not isinstance(config["groups"], dict) or not config["groups"]:
        raise ScheduleConfigurationError("'groups' must be a non-empty object.")

    anchor_date = _parse_date(config["anchor_date"])
    skipped_dates = config.get("skipped_dates", {}) or {}

    for group_name in config["group_rotation"]:
        if group_name not in config["groups"]:
            raise ScheduleConfigurationError(
                f"Group '{group_name}' is referenced in 'group_rotation' but missing from 'groups'."
            )

    for group_name, presenters in config["groups"].items():
        if not isinstance(presenters, list) or not presenters:
            raise ScheduleConfigurationError(
                f"Group '{group_name}' must contain a non-empty presenters list."
            )

    normalized_skips: Dict[str, Dict[str, str]] = {}
    for skipped_date, skip_info in skipped_dates.items():
        _parse_date(skipped_date)
        message = (skip_info or {}).get("message", "")
        if not message:
            raise ScheduleConfigurationError(
                f"Skipped date '{skipped_date}' must define a non-empty message."
            )
        normalized_skips[skipped_date] = {"message": message}

    return {
        "anchor_date": anchor_date,
        "group_rotation": list(config["group_rotation"]),
        "groups": dict(config["groups"]),
        "skipped_dates": normalized_skips,
        "path": str(path),
    }


def get_skip_info(target_date: str, config_path: Optional[str] = None) -> Optional[Dict[str, str]]:
    config = load_schedule_config(config_path)
    _parse_date(target_date)
    return config["skipped_dates"].get(target_date)


def get_presenters_for_date(target_date: str, config_path: Optional[str] = None) -> List[str]:
    config = load_schedule_config(config_path)
    meeting_date = _parse_date(target_date)

    if meeting_date < config["anchor_date"]:
        raise ScheduleConfigurationError(
            f"Date '{target_date}' is before anchor_date '{config['anchor_date'].isoformat()}'."
        )

    if target_date in config["skipped_dates"]:
        raise ScheduleConfigurationError(
            f"Date '{target_date}' is configured as a skipped meeting date."
        )

    active_meetings_count = 0
    current_date = config["anchor_date"]
    while current_date <= meeting_date:
        if current_date.isoformat() not in config["skipped_dates"]:
            active_meetings_count += 1
        current_date += timedelta(days=7)

    rotation_index = (active_meetings_count - 1) % len(config["group_rotation"])
    group_name = config["group_rotation"][rotation_index]
    return list(config["groups"][group_name])

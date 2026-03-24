from __future__ import annotations

import json
from pathlib import Path


PREFERENCES_PATH = Path(".prompt_optimizer_state.json")


def load_preferences() -> dict[str, str]:
    if not PREFERENCES_PATH.exists():
        return {}

    try:
        payload = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}

    return {
        key: str(value)
        for key, value in payload.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def save_preferences(**values: str) -> None:
    current = load_preferences()
    current.update(
        {
            key: value
            for key, value in values.items()
            if isinstance(value, str)
        }
    )
    PREFERENCES_PATH.write_text(
        json.dumps(current, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


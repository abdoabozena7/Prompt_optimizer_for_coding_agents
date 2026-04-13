from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

PREFERENCES_ENV_VAR = "PROMPT_OPTIMIZER_STATE_PATH"


def _default_preferences_path() -> Path:
    override = os.environ.get(PREFERENCES_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        base_dir = Path(
            os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
        )
        return base_dir / "PromptOptimizer" / "state.json"

    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "PromptOptimizer"
            / "state.json"
        )

    state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    base_dir = (
        Path(state_home).expanduser()
        if state_home
        else Path.home() / ".local" / "state"
    )
    return base_dir / "prompt_optimizer" / "state.json"


PREFERENCES_PATH = _default_preferences_path()


def _read_state_file() -> dict[str, Any]:
    if not PREFERENCES_PATH.exists():
        return {}

    try:
        payload = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}

    return payload


def _write_state_file(payload: dict[str, Any]) -> None:
    PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREFERENCES_PATH.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def load_preferences() -> dict[str, str]:
    payload = _read_state_file()
    return {
        key: str(value)
        for key, value in payload.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def load_app_state() -> dict[str, Any]:
    return _read_state_file()


def save_app_state(payload: dict[str, Any]) -> None:
    _write_state_file(payload)


def save_preferences(**values: str) -> None:
    current = _read_state_file()
    current.update(
        {key: value for key, value in values.items() if isinstance(value, str)}
    )
    _write_state_file(current)

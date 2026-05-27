import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def load(state_file: Path) -> dict:
    if state_file.exists():
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("State file corrupt, starting fresh")
    return {}


def save(state_file: Path, state: dict) -> None:
    state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def mark_done(state: dict, user_upn: str, item_id: str) -> None:
    state.setdefault(user_upn, {}).setdefault("done", []).append(item_id)


def is_done(state: dict, user_upn: str, item_id: str) -> bool:
    return item_id in state.get(user_upn, {}).get("done", [])


def mark_user_done(state: dict, user_upn: str) -> None:
    state.setdefault(user_upn, {})["completed"] = True


def is_user_done(state: dict, user_upn: str) -> bool:
    return state.get(user_upn, {}).get("completed", False)

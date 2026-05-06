"""Persistent mfs virtual cwd state."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mfs.errors import MfsError
from mfs.output import utc_now_iso

STATE_VERSION = 1
STATE_ENV_VAR = "MFS_STATE_PATH"


@dataclass(frozen=True)
class CwdState:
    version: int = STATE_VERSION
    default_cwd: str | None = None
    cwd_by_context: dict[str, str] = field(default_factory=dict)
    updated_at: str | None = None


def default_state_path() -> Path:
    override = os.environ.get(STATE_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".mfs" / "state.json"


def load_state(*, state_path: Path | None = None) -> CwdState:
    path = state_path or default_state_path()
    if not path.exists():
        return CwdState()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MfsError(
            code="CWD_STATE_INVALID",
            message=f"Could not read mfs cwd state at {path}",
            retryable=False,
            details={"cause": f"{type(exc).__name__}: {exc}"},
        ) from exc
    return CwdState(
        version=int(payload.get("version", STATE_VERSION)),
        default_cwd=payload.get("default_cwd"),
        cwd_by_context=dict(payload.get("cwd_by_context") or {}),
        updated_at=payload.get("updated_at"),
    )


def save_cwd(cwd: str, *, state_path: Path | None = None) -> CwdState:
    path = state_path or default_state_path()
    current = load_state(state_path=path)
    cwd_by_context = dict(current.cwd_by_context)
    context = context_key_from_cwd(cwd)
    if context:
        cwd_by_context[context] = cwd
    state = CwdState(
        version=STATE_VERSION,
        default_cwd=cwd,
        cwd_by_context=cwd_by_context,
        updated_at=utc_now_iso(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_state_payload(state), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return state


def require_cwd(*, state_path: Path | None = None) -> str:
    state = load_state(state_path=state_path)
    if not state.default_cwd:
        raise MfsError(
            code="CWD_NOT_SET",
            message="No mfs current directory is set; run mfs cd TARGET or pass TARGET explicitly",
            retryable=False,
        )
    return state.default_cwd


def state_payload(state: CwdState, *, state_path: Path | None = None) -> dict[str, Any]:
    path = state_path or default_state_path()
    return {
        "cwd": state.default_cwd,
        "context": context_key_from_cwd(state.default_cwd),
        "state_path": str(path),
        "version": state.version,
        "updated_at": state.updated_at,
    }


def context_key_from_cwd(cwd: str | None) -> str | None:
    if not cwd:
        return None
    if cwd.startswith("modal://"):
        parts = [part for part in cwd.removeprefix("modal://").split("/") if part]
        if len(parts) >= 2:
            return f"modal/{parts[0]}/{parts[1]}"
        return None
    parts = [part for part in cwd.split("/") if part]
    if len(parts) >= 4 and parts[0] == "Volumes" and parts[1] == "modal":
        return f"modal/{parts[2]}/{parts[3]}"
    return None


def _state_payload(state: CwdState) -> dict[str, Any]:
    return {
        "version": state.version,
        "default_cwd": state.default_cwd,
        "cwd_by_context": state.cwd_by_context,
        "updated_at": state.updated_at,
    }

"""JSON and human output helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import Any

import click

from mfs.errors import MfsError


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items() if item is not None}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


def echo_json(payload: Any) -> None:
    click.echo(json.dumps(to_jsonable(payload), indent=2, sort_keys=True))


def handle_error(exc: Exception, *, json_output: bool) -> None:
    if isinstance(exc, MfsError):
        if json_output:
            echo_json(exc.to_dict())
        else:
            click.echo(f"{exc.code}: {exc.message}", err=True)
        raise click.exceptions.Exit(2)
    raise exc

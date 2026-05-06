"""Stable mfs errors and JSON serialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MfsError(Exception):
    """User-facing error with a stable machine-readable code."""

    code: str
    message: str
    uri: str | None = None
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.uri is not None:
            payload["uri"] = self.uri
        if self.details:
            payload["details"] = self.details
        return {"error": payload}


def invalid_target(message: str, target: str) -> MfsError:
    return MfsError(
        code="INVALID_TARGET",
        message=message,
        uri=target,
        retryable=False,
    )

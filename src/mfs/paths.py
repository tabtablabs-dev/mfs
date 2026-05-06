"""Parse mfs virtual paths and canonical Modal URIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from mfs.errors import MfsError, invalid_target

TargetKind = Literal[
    "providers_root",
    "modal_profiles",
    "modal_environments",
    "modal_volumes",
    "modal_path",
]


@dataclass(frozen=True)
class ParsedTarget:
    raw: str
    kind: TargetKind
    profile: str | None = None
    environment: str | None = None
    volume: str | None = None
    path: str = "/"

    @property
    def canonical_uri(self) -> str:
        if self.kind != "modal_path" or not self.profile or not self.environment or not self.volume:
            return self.raw
        path = self.path if self.path.startswith("/") else f"/{self.path}"
        if path == "/":
            return f"modal://{self.profile}/{self.environment}/{self.volume}"
        return f"modal://{self.profile}/{self.environment}/{self.volume}{path}"

    @property
    def volume_uri(self) -> str:
        if self.kind != "modal_path" or not self.profile or not self.environment or not self.volume:
            return self.raw
        return f"modal://{self.profile}/{self.environment}/{self.volume}"


def parse_target(target: str) -> ParsedTarget:
    if not target or not target.strip():
        raise invalid_target("Target is required", target)
    target = target.strip()
    if target.startswith("modal://"):
        return _parse_modal_uri(target)
    return _parse_virtual_path(target)


def _parse_modal_uri(target: str) -> ParsedTarget:
    parsed = urlparse(target)
    profile = parsed.netloc
    parts = [part for part in parsed.path.split("/") if part]
    if not profile or len(parts) < 2:
        raise invalid_target(
            "Modal URI must be modal://PROFILE/ENV/VOLUME[/path] "
            "with explicit profile and environment",
            target,
        )
    environment = parts[0]
    volume = parts[1]
    remote_path = "/" + "/".join(parts[2:]) if len(parts) > 2 else "/"
    _validate_segment("PROFILE", profile, target)
    _validate_segment("ENV", environment, target)
    _validate_segment("VOLUME", volume, target)
    return ParsedTarget(
        raw=target,
        kind="modal_path",
        profile=profile,
        environment=environment,
        volume=volume,
        path=remote_path,
    )


def _parse_virtual_path(target: str) -> ParsedTarget:
    parts = _virtual_parts(target)
    if len(parts) == 1:
        return ParsedTarget(raw=target, kind="providers_root")
    _validate_modal_provider(parts, target)
    if len(parts) == 2:
        return ParsedTarget(raw=target, kind="modal_profiles")
    return _parse_modal_virtual_segments(target, parts)


def _virtual_parts(target: str) -> list[str]:
    normalized = target.rstrip("/") if target != "Volumes/" else "Volumes"
    parts = [part for part in normalized.split("/") if part]
    if not parts or parts[0] != "Volumes":
        raise invalid_target(
            "Target must be a canonical modal:// URI or virtual path "
            "Volumes/modal/PROFILE/ENV/VOLUME[/path]",
            target,
        )
    return parts


def _validate_modal_provider(parts: list[str], target: str) -> None:
    if parts[1] != "modal":
        raise invalid_target("Only the modal provider is supported in v0.0.1", target)


def _parse_modal_virtual_segments(target: str, parts: list[str]) -> ParsedTarget:
    profile = parts[2]
    _validate_segment("PROFILE", profile, target)
    if len(parts) == 3:
        return ParsedTarget(raw=target, kind="modal_environments", profile=profile)
    environment = parts[3]
    _validate_segment("ENV", environment, target)
    if len(parts) == 4:
        return ParsedTarget(
            raw=target,
            kind="modal_volumes",
            profile=profile,
            environment=environment,
        )
    return _parse_modal_volume_path(target, parts, profile, environment)


def _parse_modal_volume_path(
    target: str,
    parts: list[str],
    profile: str,
    environment: str,
) -> ParsedTarget:
    volume = parts[4]
    _validate_segment("VOLUME", volume, target)
    remote_path = "/" + "/".join(parts[5:]) if len(parts) > 5 else "/"
    return ParsedTarget(
        raw=target,
        kind="modal_path",
        profile=profile,
        environment=environment,
        volume=volume,
        path=remote_path,
    )


def _validate_segment(name: str, value: str, target: str) -> None:
    if not value or value in {".", ".."} or "/" in value:
        raise MfsError(
            code="INVALID_TARGET",
            message=f"Invalid {name} segment in target",
            uri=target,
            retryable=False,
        )

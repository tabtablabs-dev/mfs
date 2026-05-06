"""Click command surface for mfs."""

from __future__ import annotations

import asyncio
import base64
from typing import Any

import click

from mfs import __version__
from mfs.errors import MfsError
from mfs.modal_adapter import ModalAdapter, ProviderEntry
from mfs.output import echo_json, handle_error
from mfs.paths import ParsedTarget, parse_target

DEFAULT_LIMIT = 100
DEFAULT_MAX_BYTES = 64 * 1024


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def main() -> None:
    """Modal Volume filesystem/query CLI for agents."""


@main.command()
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def version(json_output: bool) -> None:
    """Print mfs version."""
    if json_output:
        echo_json({"version": __version__})
    else:
        click.echo(__version__)


@main.command()
@click.argument("target", required=False)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def doctor(target: str | None, json_output: bool) -> None:
    """Report local Modal adapter readiness without printing secrets."""
    try:
        adapter = ModalAdapter()
        parsed = parse_target(target) if target else None
        profile = parsed.profile if parsed else None
        payload: dict[str, Any] = {
            "mfs_version": __version__,
            "modal_sdk_version": adapter.sdk_version(),
            "adapter": {
                "mode": "sdk_private_proto_bounded",
                "uses_client_from_env": False,
                "profile_source": "explicit_path_segment",
                "private_proto_required": True,
                "bounded_listing": "VolumeListFiles2/VolumeListFiles max_entries",
                "bounded_cat": "VolumeGetFile2 start/len",
            },
            "profile": adapter.profile_status(profile),
            "target": _target_payload(parsed) if parsed else None,
        }
        if json_output:
            echo_json(payload)
        else:
            click.echo(f"mfs {payload['mfs_version']}")
            click.echo(f"Modal SDK: {payload['modal_sdk_version']}")
            click.echo(f"Config: {payload['profile']['config_path']}")
            if profile:
                click.echo(
                    f"Profile {profile}: configured={payload['profile']['profile_configured']} "
                    f"token_id={payload['profile']['token_id_present']} "
                    f"token_secret={payload['profile']['token_secret_present']}"
                )
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command(name="ls")
@click.argument("target")
@click.option("--recursive", is_flag=True, help="List recursively. Still bounded by --limit.")
@click.option("--limit", type=click.IntRange(1, 10_000), default=DEFAULT_LIMIT, show_default=True)
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def ls_command(target: str, recursive: bool, limit: int, timeout: float, json_output: bool) -> None:
    """List virtual roots, environments, volumes, or remote Volume paths."""
    try:
        parsed = parse_target(target)
        payload = asyncio.run(
            _list_target(parsed, recursive=recursive, limit=limit, timeout=timeout)
        )
        if json_output:
            echo_json(payload)
        else:
            _print_entries(payload.get("entries", []))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command()
@click.argument("target")
@click.option("--limit", type=click.IntRange(1, 10_000), default=DEFAULT_LIMIT, show_default=True)
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def stat(target: str, limit: int, timeout: float, json_output: bool) -> None:
    """Stat a Modal Volume root, file, or directory path."""
    try:
        parsed = parse_target(target)
        adapter = ModalAdapter(timeout=timeout)
        if parsed.kind != "modal_path":
            raise MfsError(
                code="INVALID_TARGET",
                message="stat requires Volumes/modal/PROFILE/ENV/VOLUME[/path] or modal://PROFILE/ENV/VOLUME[/path]",
                uri=target,
            )
        payload = asyncio.run(adapter.stat_path(parsed, limit=limit))
        if json_output:
            echo_json(payload)
        else:
            entry = payload["entry"]
            if isinstance(entry, dict):
                click.echo(f"{entry.get('type')} {entry.get('path')}")
            else:
                click.echo(f"{getattr(entry, 'type', payload.get('type'))} {target}")
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command()
@click.argument("target")
@click.option("--bytes", "byte_range", metavar="START:LEN", help="Read a bounded byte range.")
@click.option("--max-bytes", type=click.IntRange(1), default=DEFAULT_MAX_BYTES, show_default=True)
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def cat(
    target: str, byte_range: str | None, max_bytes: int, timeout: float, json_output: bool
) -> None:
    """Read a bounded byte slice from a remote file."""
    try:
        parsed = parse_target(target)
        start, length = _parse_byte_range(byte_range, max_bytes=max_bytes)
        adapter = ModalAdapter(timeout=timeout)
        result = asyncio.run(
            adapter.cat_bytes(parsed, start=start, length=length, max_bytes=max_bytes)
        )
        if json_output:
            echo_json(result)
            return
        if result.encoding == "base64":
            data = base64.b64decode(result.content)
        else:
            data = result.content.encode("utf-8")
        click.get_binary_stream("stdout").write(data)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


async def _list_target(
    parsed: ParsedTarget,
    *,
    recursive: bool,
    limit: int,
    timeout: float,
) -> dict[str, Any]:
    adapter = ModalAdapter(timeout=timeout)
    if parsed.kind == "providers_root":
        entries = [ProviderEntry(name="modal")]
        return _list_payload(parsed, entries, recursive=recursive, limit=limit)
    if parsed.kind == "modal_profiles":
        entries = adapter.list_profiles()
        return _list_payload(parsed, entries, recursive=recursive, limit=limit)
    if parsed.kind == "modal_environments":
        entries = await adapter.list_environments(parsed.profile or "")
        return _list_payload(parsed, entries, recursive=recursive, limit=limit)
    if parsed.kind == "modal_volumes":
        entries = await adapter.list_volumes(
            parsed.profile or "",
            parsed.environment or "",
            limit=limit,
        )
        return _list_payload(parsed, entries, recursive=recursive, limit=limit)
    entries = await adapter.list_files(parsed, recursive=recursive, limit=limit)
    return _list_payload(
        parsed, entries, recursive=recursive, limit=limit, uri=parsed.canonical_uri
    )


def _list_payload(
    parsed: ParsedTarget,
    entries: list[Any],
    *,
    recursive: bool,
    limit: int,
    uri: str | None = None,
) -> dict[str, Any]:
    return {
        "target": _target_payload(parsed),
        "uri": uri or parsed.raw,
        "recursive": recursive,
        "limit": limit,
        "count": len(entries),
        "maybe_truncated": len(entries) >= limit,
        "entries": entries,
    }


def _target_payload(parsed: ParsedTarget | None) -> dict[str, Any] | None:
    if parsed is None:
        return None
    return {
        "raw": parsed.raw,
        "kind": parsed.kind,
        "profile": parsed.profile,
        "environment": parsed.environment,
        "volume": parsed.volume,
        "path": parsed.path,
        "canonical_uri": parsed.canonical_uri,
    }


def _print_entries(entries: list[Any]) -> None:
    for entry in entries:
        if isinstance(entry, dict):
            type_label = entry.get("type", "")
            name = entry.get("name") or entry.get("path") or ""
            size = entry.get("size", "")
        else:
            type_label = getattr(entry, "type", "")
            name = getattr(entry, "name", "") or getattr(entry, "path", "")
            size = getattr(entry, "size", "") or ""
        click.echo(f"{type_label}\t{size}\t{name}")


def _parse_byte_range(byte_range: str | None, *, max_bytes: int) -> tuple[int, int]:
    if byte_range is None:
        return 0, max_bytes
    try:
        start_text, length_text = byte_range.split(":", 1)
        start = int(start_text)
        length = int(length_text)
    except ValueError as exc:
        raise MfsError(
            code="INVALID_BYTE_RANGE",
            message="--bytes must use START:LEN with non-negative integers",
            retryable=False,
        ) from exc
    if start < 0 or length < 1:
        raise MfsError(
            code="INVALID_BYTE_RANGE",
            message="--bytes START must be >= 0 and LEN must be >= 1",
            retryable=False,
        )
    if length > max_bytes:
        raise MfsError(
            code="BYTE_LIMIT_EXCEEDED",
            message="Requested byte range exceeds --max-bytes",
            retryable=False,
            details={"requested_len": length, "max_bytes": max_bytes},
        )
    return start, length


if __name__ == "__main__":
    main()

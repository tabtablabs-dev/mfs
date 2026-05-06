#!/usr/bin/env python3
"""Spike Modal profile-scoped Volume access and bounded RPCs.

Run with:

    uv run --with 'modal==1.3.5' python spikes/001-modal-profile-adapter/main.py \
      --profile tabtablabs --environment main --json

The script is read-only against Modal Volumes. It does not print raw volume
names, file paths, signed URLs, tokens, or file contents unless --show-names is
explicitly passed for local debugging.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from typing import Any

import aiohttp
import modal
from modal.client import _Client
from modal.config import config
from modal.volume import FileEntryType, _VolumeManager
from modal_proto import api_pb2

V1_VALUES = {
    None,
    0,
    api_pb2.VolumeFsVersion.VOLUME_FS_VERSION_UNSPECIFIED,
    api_pb2.VolumeFsVersion.VOLUME_FS_VERSION_V1,
}


@dataclass(frozen=True)
class RedactedFile:
    path_hash: str
    type: str
    size: int
    mtime: int


@dataclass(frozen=True)
class RedactedVolume:
    idx: int
    name_hash: str
    object_id_hash: str
    metadata_version: str
    list_rpc: str | None
    bounded_count: int | None
    bounded_cap: int
    sample_recursive: bool
    sample_entries: list[RedactedFile]
    list_error: str | None = None
    raw_name: str | None = None


@dataclass(frozen=True)
class RangeProbe:
    attempted: bool
    skipped_reason: str | None
    volume_idx: int | None
    metadata_version: str | None
    list_rpc: str | None
    file_path_hash: str | None
    requested_len: int | None
    response_size: int | None
    response_start: int | None
    response_len: int | None
    downloaded_len: int | None
    downloaded_sha256_prefix: str | None
    url_count: int | None


@dataclass(frozen=True)
class SpikeResult:
    modal_version: str
    profile: str
    environment: str
    modal_profile_env: str | None
    active_profile_is_required: bool
    explicit_profile_token_present: bool
    public_volume_list_count: int
    public_volume_list_cap: int
    volumes: list[RedactedVolume]
    range_probe: RangeProbe
    verdict: str
    notes: list[str]


def stable_hash(value: str | None) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:12]


def version_label(value: int | None) -> str:
    if value in V1_VALUES:
        return "v1"
    if value == api_pb2.VolumeFsVersion.VOLUME_FS_VERSION_V2:
        return "v2"
    return f"unknown:{value}"


def redact_entry(entry: Any) -> RedactedFile:
    file_type = getattr(entry, "type", None)
    if isinstance(file_type, FileEntryType):
        type_label = file_type.name.lower()
    else:
        try:
            type_label = FileEntryType(file_type).name.lower()
        except Exception:
            type_label = str(file_type)
    return RedactedFile(
        path_hash=stable_hash(getattr(entry, "path", "")),
        type=type_label,
        size=int(getattr(entry, "size", 0) or 0),
        mtime=int(getattr(entry, "mtime", 0) or 0),
    )


def get_profile_credentials(profile: str) -> tuple[str, str, str]:
    """Resolve credentials for an explicit Modal profile.

    Deliberately use use_env=False so a process-level MODAL_PROFILE or token env
    cannot silently redirect an explicit mfs path segment.
    """

    token_id = config.get("token_id", profile=profile, use_env=False)
    token_secret = config.get("token_secret", profile=profile, use_env=False)
    server_url = config.get("server_url", profile=profile, use_env=False)
    if not token_id or not token_secret:
        raise RuntimeError(f"profile {profile!r} has no token_id/token_secret in Modal config")
    return server_url, token_id, token_secret


def is_version_mismatch(exc: Exception) -> bool:
    message = str(exc).lower()
    return "not supported" in message and "volume" in message


async def list_files_bounded(
    volume: Any,
    *,
    path: str,
    recursive: bool,
    max_entries: int,
    timeout_seconds: float,
) -> tuple[list[Any], str]:
    async def collect(api_name: str) -> list[Any]:
        if api_name == "v2":
            request = api_pb2.VolumeListFiles2Request(
                volume_id=volume.object_id,
                path=path,
                recursive=recursive,
                max_entries=max_entries,
            )
            stream = volume._client.stub.VolumeListFiles2.unary_stream(request)
        else:
            request = api_pb2.VolumeListFilesRequest(
                volume_id=volume.object_id,
                path=path,
                recursive=recursive,
                max_entries=max_entries,
            )
            stream = volume._client.stub.VolumeListFiles.unary_stream(request)

        entries = []
        async for batch in stream:
            entries.extend(batch.entries)
            if len(entries) > max_entries:
                raise RuntimeError(
                    f"Modal returned {len(entries)} entries despite max_entries={max_entries}"
                )
        return entries

    last_mismatch: Exception | None = None
    for api_name in ("v2", "v1"):
        try:
            entries = await asyncio.wait_for(collect(api_name), timeout=timeout_seconds)
            return entries, api_name
        except Exception as exc:  # noqa: BLE001 - spike records SDK/proto behavior.
            if is_version_mismatch(exc):
                last_mismatch = exc
                continue
            raise
    assert last_mismatch is not None
    raise last_mismatch


async def download_signed_urls(urls: list[str], *, byte_cap: int) -> tuple[int, str]:
    data = bytearray()
    async with aiohttp.ClientSession() as session:
        for url in urls:
            async with session.get(url) as response:
                response.raise_for_status()
                async for chunk in response.content.iter_chunked(8192):
                    data.extend(chunk)
                    if len(data) > byte_cap:
                        raise RuntimeError(f"range download exceeded byte cap {byte_cap}")
    return len(data), hashlib.sha256(data).hexdigest()[:12]


async def probe_range_read(
    volumes: list[Any],
    *,
    max_entries_per_volume: int,
    range_bytes: int,
    safe_download_cap: int,
    rpc_timeout_seconds: float,
) -> RangeProbe:
    for idx, volume in enumerate(volumes):
        try:
            entries, list_rpc = await list_files_bounded(
                volume,
                path="/",
                recursive=True,
                max_entries=max_entries_per_volume,
                timeout_seconds=rpc_timeout_seconds,
            )
        except Exception:  # noqa: BLE001 - skip volumes too large/unsupported for range discovery.
            continue
        files = [
            entry
            for entry in entries
            if getattr(entry, "type", None) == FileEntryType.FILE
            and 0 < int(getattr(entry, "size", 0) or 0) <= safe_download_cap
        ]
        if not files:
            continue

        entry = files[0]
        requested_len = min(range_bytes, int(entry.size))
        request = api_pb2.VolumeGetFile2Request(
            volume_id=volume.object_id,
            path=entry.path,
            start=0,
            len=requested_len,
        )
        response = await asyncio.wait_for(
            volume._client.stub.VolumeGetFile2(request),
            timeout=rpc_timeout_seconds,
        )
        urls = list(response.get_urls)
        downloaded_len, downloaded_hash = await download_signed_urls(
            urls,
            byte_cap=max(requested_len, 1) + 1024,
        )
        metadata_version = version_label(getattr(getattr(volume, "_metadata", None), "version", None))
        return RangeProbe(
            attempted=True,
            skipped_reason=None,
            volume_idx=idx,
            metadata_version=metadata_version,
            list_rpc=list_rpc,
            file_path_hash=stable_hash(entry.path),
            requested_len=requested_len,
            response_size=int(response.size),
            response_start=int(response.start),
            response_len=int(response.len),
            downloaded_len=downloaded_len,
            downloaded_sha256_prefix=downloaded_hash,
            url_count=len(urls),
        )

    return RangeProbe(
        attempted=False,
        skipped_reason=f"no non-empty file <= {safe_download_cap} bytes found in bounded probes",
        volume_idx=None,
        metadata_version=None,
        list_rpc=None,
        file_path_hash=None,
        requested_len=None,
        response_size=None,
        response_start=None,
        response_len=None,
        downloaded_len=None,
        downloaded_sha256_prefix=None,
        url_count=None,
    )


async def run(args: argparse.Namespace) -> SpikeResult:
    server_url, token_id, token_secret = get_profile_credentials(args.profile)
    explicit_profile_token_present = bool(token_id and token_secret)

    # Prove active MODAL_PROFILE is not required for explicit profile resolution.
    active_profile_is_required = False

    async with _Client(
        server_url,
        api_pb2.CLIENT_TYPE_CLIENT,
        (token_id, token_secret),
    ) as client:
        volumes = await asyncio.wait_for(
            _VolumeManager.list(
                max_objects=args.max_volumes,
                environment_name=args.environment,
                client=client,
            ),
            timeout=args.rpc_timeout,
        )

        redacted_volumes: list[RedactedVolume] = []
        for idx, volume in enumerate(volumes):
            metadata = getattr(volume, "_metadata", None)
            metadata_version = version_label(getattr(metadata, "version", None))
            name = getattr(metadata, "name", None) or getattr(volume, "name", None)
            base_kwargs = dict(
                idx=idx,
                name_hash=stable_hash(name),
                object_id_hash=stable_hash(volume.object_id),
                metadata_version=metadata_version,
                bounded_cap=args.max_entries,
                sample_recursive=args.recursive_sample,
                raw_name=name if args.show_names else None,
            )
            try:
                entries, list_rpc = await list_files_bounded(
                    volume,
                    path="/",
                    recursive=args.recursive_sample,
                    max_entries=args.max_entries,
                    timeout_seconds=args.rpc_timeout,
                )
            except Exception as exc:  # noqa: BLE001 - record broad-path/SDK behavior.
                redacted_volumes.append(
                    RedactedVolume(
                        **base_kwargs,
                        list_rpc=None,
                        bounded_count=None,
                        sample_entries=[],
                        list_error=f"{type(exc).__name__}: {str(exc)}",
                    )
                )
                continue
            redacted_volumes.append(
                RedactedVolume(
                    **base_kwargs,
                    list_rpc=list_rpc,
                    bounded_count=len(entries),
                    sample_entries=[redact_entry(entry) for entry in entries[: args.sample_entries]],
                    list_error=None,
                )
            )

        range_probe = await probe_range_read(
            volumes,
            max_entries_per_volume=args.range_scan_entries,
            range_bytes=args.range_bytes,
            safe_download_cap=args.safe_download_cap,
            rpc_timeout_seconds=args.rpc_timeout,
        )

    notes = [
        "Used explicit profile credentials via modal.config.Config.get(profile=..., use_env=False).",
        "Avoided Client.from_env() because it is a process singleton and ignores later override configs once cached.",
        "Used private modal.client._Client plus private _VolumeManager.list(client=...) for per-profile client injection; the public synchronicity wrapper hung when called with a direct private client outside Modal's task context.",
        "Used private/proto VolumeListFiles{1,2}Request.max_entries for bounded listings; public Volume.listdir/iterdir do not expose max_entries.",
        "Used private/proto VolumeGetFile2Request.start/len for bounded byte-range reads; public Volume.read_file does not expose range parameters.",
    ]
    list_error_count = sum(1 for volume in redacted_volumes if volume.list_error)
    if list_error_count:
        notes.append(
            f"{list_error_count} volume root listing probe(s) failed even with max_entries; mfs must surface path-too-broad errors and avoid assuming root listings are always enumerable."
        )
    if range_probe.attempted and range_probe.downloaded_len == range_probe.requested_len:
        verdict = "VALIDATED"
    elif range_probe.attempted:
        verdict = "PARTIAL"
        notes.append("Range RPC returned bytes, but downloaded length did not exactly match requested_len.")
    else:
        verdict = "PARTIAL"
        notes.append("Could not find a small file in bounded probes to verify range download; list/profile parts still validated.")

    return SpikeResult(
        modal_version=getattr(modal, "__version__", "unknown"),
        profile=args.profile,
        environment=args.environment,
        modal_profile_env=os.environ.get("MODAL_PROFILE"),
        active_profile_is_required=active_profile_is_required,
        explicit_profile_token_present=explicit_profile_token_present,
        public_volume_list_count=len(volumes),
        public_volume_list_cap=args.max_volumes,
        volumes=redacted_volumes,
        range_probe=range_probe,
        verdict=verdict,
        notes=notes,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="tabtablabs")
    parser.add_argument("--environment", default="main")
    parser.add_argument("--max-volumes", type=int, default=25)
    parser.add_argument("--max-entries", type=int, default=3)
    parser.add_argument("--sample-entries", type=int, default=3)
    parser.add_argument("--range-scan-entries", type=int, default=50)
    parser.add_argument("--range-bytes", type=int, default=64)
    parser.add_argument("--safe-download-cap", type=int, default=512 * 1024)
    parser.add_argument("--rpc-timeout", type=float, default=20.0)
    parser.add_argument("--recursive-sample", action="store_true")
    parser.add_argument("--show-names", action="store_true", help="print raw names; do not commit output")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = asyncio.run(run(args))
    payload = asdict(result)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Verdict: {result.verdict}")
        print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

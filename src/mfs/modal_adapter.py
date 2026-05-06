"""Modal SDK adapter for mfs v0.0.1.

The adapter intentionally uses a small amount of Modal private API to preserve
bounded agent semantics that Modal's public Python SDK does not expose in 1.3.5.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from mfs.errors import MfsError
from mfs.output import utc_now_iso
from mfs.paths import ParsedTarget


@dataclass(frozen=True)
class FsEntry:
    path: str
    name: str
    type: str
    size: int | None = None
    mtime: int | None = None


@dataclass(frozen=True)
class VolumeEntry:
    name: str
    type: str = "volume"
    volume_id: str | None = None
    created_at: float | None = None
    created_by: str | None = None
    metadata_version: int | None = None


@dataclass(frozen=True)
class EnvironmentEntry:
    name: str
    type: str = "environment"
    default: bool | None = None
    environment_id: str | None = None
    webhook_suffix: str | None = None


@dataclass(frozen=True)
class ProfileEntry:
    name: str
    type: str = "profile"


@dataclass(frozen=True)
class ProviderEntry:
    name: str
    type: str = "provider"


@dataclass(frozen=True)
class CatResult:
    uri: str
    path: str
    start: int
    requested_len: int
    response_start: int
    response_len: int
    size: int
    downloaded_len: int
    truncated: bool
    encoding: str
    content: str
    read_at: str


class ModalAdapter:
    """Thin, bounded Modal adapter."""

    def __init__(self, *, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self._modal_bundle: dict[str, Any] | None = None

    def bundle(self) -> dict[str, Any]:
        if self._modal_bundle is not None:
            return self._modal_bundle
        try:
            import modal
            import modal.exception as modal_exception
            from google.protobuf.empty_pb2 import Empty
            from modal.client import _Client
            from modal.config import config, config_profiles, user_config_path
            from modal.volume import FileEntryType, _Volume, _VolumeManager
            from modal_proto import api_pb2
        except Exception as exc:  # noqa: BLE001 - converted to a stable CLI error.
            raise MfsError(
                code="MODAL_SDK_UNAVAILABLE",
                message="Modal Python SDK is unavailable; install mfs with its Modal dependency",
                retryable=False,
                details={"cause": f"{type(exc).__name__}: {exc}"},
            ) from exc
        self._modal_bundle = {
            "modal": modal,
            "modal_exception": modal_exception,
            "Empty": Empty,
            "_Client": _Client,
            "config": config,
            "config_profiles": config_profiles,
            "user_config_path": user_config_path,
            "FileEntryType": FileEntryType,
            "_Volume": _Volume,
            "_VolumeManager": _VolumeManager,
            "api_pb2": api_pb2,
        }
        return self._modal_bundle

    def sdk_version(self) -> str | None:
        modal = self.bundle()["modal"]
        return getattr(modal, "__version__", None)

    def config_path(self) -> str:
        return str(self.bundle()["user_config_path"])

    def list_profiles(self) -> list[ProfileEntry]:
        profiles = sorted(str(profile) for profile in self.bundle()["config_profiles"]())
        return [ProfileEntry(name=profile) for profile in profiles]

    def profile_status(self, profile: str | None = None) -> dict[str, Any]:
        bundle = self.bundle()
        config = bundle["config"]
        profiles = {str(item) for item in bundle["config_profiles"]()}
        payload: dict[str, Any] = {
            "config_path": self.config_path(),
            "configured_profiles": sorted(profiles),
            "profile": profile,
        }
        if profile is None:
            return payload
        payload["profile_configured"] = profile in profiles
        payload["token_id_present"] = bool(config.get("token_id", profile=profile, use_env=False))
        payload["token_secret_present"] = bool(
            config.get("token_secret", profile=profile, use_env=False)
        )
        payload["server_url"] = config.get("server_url", profile=profile, use_env=False)
        return payload

    async def list_environments(self, profile: str) -> list[EnvironmentEntry]:
        bundle = self.bundle()
        Empty = bundle["Empty"]
        async with self.client(profile) as client:
            try:
                response = await asyncio.wait_for(
                    client.stub.EnvironmentList(Empty()), timeout=self.timeout
                )
            except Exception as exc:  # noqa: BLE001
                raise self._convert_modal_error(exc, uri=f"modal://{profile}") from exc
        entries = []
        for item in response.items:
            entries.append(
                EnvironmentEntry(
                    name=item.name,
                    default=bool(getattr(item, "default", False)),
                    environment_id=item.environment_id or None,
                    webhook_suffix=item.webhook_suffix or None,
                )
            )
        return entries

    async def list_volumes(
        self, profile: str, environment: str, *, limit: int
    ) -> list[VolumeEntry]:
        bundle = self.bundle()
        volume_manager = bundle["_VolumeManager"]()
        async with self.client(profile) as client:
            try:
                volumes = await asyncio.wait_for(
                    volume_manager.list(
                        max_objects=limit,
                        environment_name=environment,
                        client=client,
                    ),
                    timeout=self.timeout,
                )
            except Exception as exc:  # noqa: BLE001
                raise self._convert_modal_error(
                    exc,
                    uri=f"modal://{profile}/{environment}",
                ) from exc
        return [self._volume_entry_from_volume(volume) for volume in volumes]

    async def stat_path(self, target: ParsedTarget, *, limit: int) -> dict[str, Any]:
        self._require_modal_path(target)
        if target.path == "/":
            async with self.client(target.profile or "") as client:
                volume = await self._hydrate_volume(target, client)
            return {
                "uri": target.volume_uri,
                "type": "volume",
                "entry": self._volume_entry_from_volume(volume),
            }

        entries = await self.list_files(target, recursive=False, limit=max(limit, 2))
        exact = _find_exact_entry(entries, target.path)
        if exact is not None:
            return {"uri": target.canonical_uri, "type": exact.type, "entry": exact}
        return {
            "uri": target.canonical_uri,
            "type": "directory",
            "entry": {
                "path": target.path,
                "name": PurePosixPath(target.path).name,
                "type": "directory",
                "child_count_limited": len(entries),
            },
        }

    async def list_files(
        self, target: ParsedTarget, *, recursive: bool, limit: int
    ) -> list[FsEntry]:
        self._require_modal_path(target)
        async with self.client(target.profile or "") as client:
            volume = await self._hydrate_volume(target, client)
            proto_entries, _rpc = await self._list_proto_entries(
                volume,
                path=target.path,
                recursive=recursive,
                max_entries=limit,
                uri=target.canonical_uri,
            )
        return [self._entry_from_proto(entry) for entry in proto_entries]

    async def cat_bytes(
        self,
        target: ParsedTarget,
        *,
        start: int,
        length: int,
        max_bytes: int,
    ) -> CatResult:
        self._require_modal_path(target)
        if length > max_bytes:
            raise MfsError(
                code="BYTE_LIMIT_EXCEEDED",
                message="Requested byte range exceeds --max-bytes",
                uri=target.canonical_uri,
                retryable=False,
                details={"requested_len": length, "max_bytes": max_bytes},
            )
        async with self.client(target.profile or "") as client:
            volume = await self._hydrate_volume(target, client)
            response = await self._get_file_response(
                client,
                volume,
                target,
                start=start,
                length=length,
            )
            data = await self._download_response_urls(
                response, uri=target.canonical_uri, max_bytes=max_bytes
            )
        return _cat_result_from_bytes(target, response, data, requested_len=length)

    async def _get_file_response(
        self,
        client: Any,
        volume: Any,
        target: ParsedTarget,
        *,
        start: int,
        length: int,
    ) -> Any:
        api_pb2 = self.bundle()["api_pb2"]
        request = api_pb2.VolumeGetFile2Request(
            volume_id=volume.object_id,
            path=target.path,
            start=start,
            len=length,
        )
        try:
            return await asyncio.wait_for(
                client.stub.VolumeGetFile2(request),
                timeout=self.timeout,
            )
        except MfsError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._convert_modal_error(exc, uri=target.canonical_uri) from exc

    async def _download_response_urls(self, response: Any, *, uri: str, max_bytes: int) -> bytes:
        try:
            return await asyncio.wait_for(
                self._download_signed_urls(list(response.get_urls), byte_cap=max_bytes),
                timeout=self.timeout,
            )
        except MfsError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._convert_modal_error(exc, uri=uri) from exc

    @contextlib.asynccontextmanager
    async def client(self, profile: str) -> AsyncIterator[Any]:
        bundle = self.bundle()
        _Client = bundle["_Client"]
        api_pb2 = bundle["api_pb2"]
        server_url, token_id, token_secret = self._profile_credentials(profile)
        async with _Client(
            server_url, api_pb2.CLIENT_TYPE_CLIENT, (token_id, token_secret)
        ) as client:
            yield client

    def _profile_credentials(self, profile: str) -> tuple[str, str, str]:
        bundle = self.bundle()
        config = bundle["config"]
        profiles = {str(item) for item in bundle["config_profiles"]()}
        if profile not in profiles:
            raise MfsError(
                code="MODAL_PROFILE_NOT_FOUND",
                message=f"Modal profile {profile!r} is not configured",
                retryable=False,
                details={
                    "config_path": self.config_path(),
                    "configured_profiles": sorted(profiles),
                },
            )
        token_id = config.get("token_id", profile=profile, use_env=False)
        token_secret = config.get("token_secret", profile=profile, use_env=False)
        server_url = config.get("server_url", profile=profile, use_env=False)
        if not token_id or not token_secret:
            raise MfsError(
                code="MODAL_AUTH_MISSING",
                message=f"Modal profile {profile!r} has no token_id/token_secret in config",
                retryable=False,
                details={"config_path": self.config_path()},
            )
        return server_url, token_id, token_secret

    def _volume_entry_from_volume(self, volume: Any) -> VolumeEntry:
        metadata = getattr(volume, "_metadata", None)
        creation_info = getattr(metadata, "creation_info", None)
        return VolumeEntry(
            name=getattr(metadata, "name", None) or getattr(volume, "name", None) or "",
            volume_id=getattr(volume, "object_id", None),
            created_at=getattr(creation_info, "created_at", None),
            created_by=getattr(creation_info, "created_by", None) or None,
            metadata_version=getattr(metadata, "version", None),
        )

    async def _hydrate_volume(self, target: ParsedTarget, client: Any) -> Any:
        bundle = self.bundle()
        volume_cls = bundle["_Volume"]
        try:
            volume = volume_cls.from_name(
                target.volume or "",
                environment_name=target.environment,
                client=client,
            )
            return await asyncio.wait_for(volume.hydrate(client), timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001
            raise self._convert_modal_error(exc, uri=target.volume_uri) from exc

    async def _list_proto_entries(
        self,
        volume: Any,
        *,
        path: str,
        recursive: bool,
        max_entries: int,
        uri: str,
    ) -> tuple[list[Any], str]:
        bundle = self.bundle()
        api_pb2 = bundle["api_pb2"]
        last_mismatch: Exception | None = None
        for api_name in ("v2", "v1"):
            try:
                stream = _volume_list_stream(
                    volume,
                    api_pb2=api_pb2,
                    api_name=api_name,
                    path=path,
                    recursive=recursive,
                    max_entries=max_entries,
                )
                entries = await asyncio.wait_for(
                    _collect_stream(stream, max_entries), timeout=self.timeout
                )
                return entries, api_name
            except MfsError:
                raise
            except Exception as exc:  # noqa: BLE001
                if not _is_version_mismatch(exc):
                    raise self._convert_modal_error(exc, uri=uri) from exc
                last_mismatch = exc
        assert last_mismatch is not None
        raise self._convert_modal_error(last_mismatch, uri=uri)

    def _entry_from_proto(self, entry: Any) -> FsEntry:
        FileEntryType = self.bundle()["FileEntryType"]
        try:
            type_label = FileEntryType(entry.type).name.lower()
        except Exception:  # noqa: BLE001
            type_label = str(entry.type)
        path = entry.path or "/"
        return FsEntry(
            path=path,
            name=PurePosixPath(path).name or "/",
            type=type_label,
            size=int(entry.size) if entry.size is not None else None,
            mtime=int(entry.mtime) if entry.mtime is not None else None,
        )

    async def _download_signed_urls(self, urls: list[str], *, byte_cap: int) -> bytes:
        try:
            import aiohttp
        except Exception as exc:  # noqa: BLE001
            raise MfsError(
                code="AIOHTTP_UNAVAILABLE",
                message="aiohttp is required for bounded Modal file downloads",
                retryable=False,
            ) from exc
        data = bytearray()
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for url in urls:
                async with session.get(url) as response:
                    response.raise_for_status()
                    async for chunk in response.content.iter_chunked(8192):
                        data.extend(chunk)
                        if len(data) > byte_cap:
                            raise MfsError(
                                code="BYTE_LIMIT_EXCEEDED",
                                message="Downloaded data exceeded byte cap",
                                retryable=False,
                                details={"max_bytes": byte_cap},
                            )
        return bytes(data)

    def _convert_modal_error(self, exc: Exception, *, uri: str | None) -> MfsError:
        message = str(exc)
        name = type(exc).__name__
        if "Too many files to list in the path" in message:
            return MfsError(
                code="PATH_TOO_BROAD",
                message="Path is too broad for Modal to list safely; narrow the prefix",
                uri=uri,
                retryable=False,
                details={"modal_error": message},
            )
        if name in {"NotFoundError"} or "not found" in message.lower():
            return MfsError(
                code="REMOTE_NOT_FOUND", message=message or "Remote object not found", uri=uri
            )
        if name in {"AuthError", "InvalidError"} and "token" in message.lower():
            return MfsError(code="MODAL_AUTH_ERROR", message=message, uri=uri, retryable=False)
        if isinstance(exc, TimeoutError | asyncio.TimeoutError):
            return MfsError(
                code="REMOTE_TIMEOUT",
                message="Modal operation timed out",
                uri=uri,
                retryable=True,
                details={"timeout_seconds": self.timeout},
            )
        return MfsError(
            code="MODAL_ERROR",
            message=message or name,
            uri=uri,
            retryable=False,
            details={"modal_exception": name},
        )

    def _require_modal_path(self, target: ParsedTarget) -> None:
        if (
            target.kind != "modal_path"
            or not target.profile
            or not target.environment
            or not target.volume
        ):
            raise MfsError(
                code="INVALID_TARGET",
                message="Command requires a Modal Volume path",
                uri=target.raw,
                retryable=False,
            )


def _volume_list_stream(
    volume: Any,
    *,
    api_pb2: Any,
    api_name: str,
    path: str,
    recursive: bool,
    max_entries: int,
) -> Any:
    request_cls = (
        api_pb2.VolumeListFiles2Request if api_name == "v2" else api_pb2.VolumeListFilesRequest
    )
    request = request_cls(
        volume_id=volume.object_id,
        path=path,
        recursive=recursive,
        max_entries=max_entries,
    )
    rpc = (
        volume._client.stub.VolumeListFiles2
        if api_name == "v2"
        else volume._client.stub.VolumeListFiles
    )
    return rpc.unary_stream(request)


async def _collect_stream(stream: Any, max_entries: int) -> list[Any]:
    entries = []
    async for batch in stream:
        entries.extend(batch.entries)
        if len(entries) > max_entries:
            raise MfsError(
                code="REMOTE_LIMIT_EXCEEDED",
                message="Modal returned more entries than requested max_entries",
                retryable=False,
                details={"max_entries": max_entries},
            )
    return entries


def _is_version_mismatch(exc: Exception) -> bool:
    message = str(exc).lower()
    return "not supported" in message and "volume" in message


def _normalize_modal_path(path: str) -> str:
    stripped = path.strip("/")
    return f"/{stripped}" if stripped else "/"


def _find_exact_entry(entries: list[FsEntry], path: str) -> FsEntry | None:
    normalized = _normalize_modal_path(path)
    for entry in entries:
        if _normalize_modal_path(entry.path) == normalized:
            return entry
    return None


def _cat_result_from_bytes(
    target: ParsedTarget, response: Any, data: bytes, *, requested_len: int
) -> CatResult:
    try:
        content = data.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        content = base64.b64encode(data).decode("ascii")
        encoding = "base64"
    response_start = int(response.start)
    downloaded_len = len(data)
    size = int(response.size)
    return CatResult(
        uri=target.canonical_uri,
        path=target.path,
        start=response_start,
        requested_len=requested_len,
        response_start=response_start,
        response_len=int(response.len),
        size=size,
        downloaded_len=downloaded_len,
        truncated=response_start + downloaded_len < size,
        encoding=encoding,
        content=content,
        read_at=utc_now_iso(),
    )

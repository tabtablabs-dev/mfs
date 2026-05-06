"""Click command surface for mfs."""

from __future__ import annotations

import asyncio
import base64
import fnmatch
import json
import re
from pathlib import Path
from typing import Any

import click

from mfs import __version__
from mfs.errors import MfsError
from mfs.index import IndexStore
from mfs.modal_adapter import ModalAdapter, ProviderEntry
from mfs.output import echo_json, handle_error, to_jsonable, utc_now_iso
from mfs.paths import ParsedTarget, parse_target, resolve_target
from mfs.state import default_state_path, load_state, save_cwd, state_payload

DEFAULT_LIMIT = 100
DEFAULT_MAX_BYTES = 64 * 1024
DEFAULT_DU_DEPTH = 8
DEFAULT_DU_LIMIT = 10_000


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
@click.argument("target", required=False)
@click.option("-a", "--all", "include_hidden", is_flag=True, help="Include dotfiles.")
@click.option("-l", "long_format", is_flag=True, help="Print Modal metadata long format.")
@click.option("--recursive", is_flag=True, help="List recursively. Still bounded by --limit.")
@click.option("--limit", type=click.IntRange(1, 10_000), default=DEFAULT_LIMIT, show_default=True)
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def ls_command(
    target: str | None,
    include_hidden: bool,
    long_format: bool,
    recursive: bool,
    limit: int,
    timeout: float,
    json_output: bool,
) -> None:
    """List virtual roots, environments, volumes, or remote Volume paths."""
    try:
        parsed = resolve_target(target)
        payload = asyncio.run(
            _list_target(parsed, recursive=recursive, limit=limit, timeout=timeout)
        )
        entries = _filter_hidden(payload.get("entries", []), include_hidden=include_hidden)
        payload["entries"] = entries
        payload["count"] = len(entries)
        payload["include_hidden"] = include_hidden
        payload["long_format"] = long_format
        if json_output:
            echo_json(payload)
        else:
            _print_entries(payload.get("entries", []), long_format=long_format)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command()
@click.argument("target", required=False)
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def cd(target: str | None, timeout: float, json_output: bool) -> None:
    """Set the persistent mfs virtual current directory."""
    try:
        parsed = parse_target("Volumes/") if target is None else resolve_target(target)
        cwd = _cwd_value(parsed)
        if parsed.kind == "modal_path" and parsed.path != "/":
            adapter = ModalAdapter(timeout=timeout)
            stat_payload = asyncio.run(adapter.stat_path(parsed, limit=2))
            if stat_payload.get("type") == "file":
                raise MfsError(
                    code="CWD_NOT_DIRECTORY",
                    message="mfs cd target must be a directory-like remote target",
                    uri=parsed.canonical_uri,
                    retryable=False,
                )
        state = save_cwd(cwd)
        payload = state_payload(state, state_path=default_state_path())
        if json_output:
            echo_json(payload)
        else:
            click.echo(cwd)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command()
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def pwd(json_output: bool) -> None:
    """Print the persistent mfs virtual current directory."""
    try:
        state = load_state()
        if not state.default_cwd:
            raise MfsError(
                code="CWD_NOT_SET",
                message="No mfs current directory is set; run mfs cd TARGET first",
                retryable=False,
            )
        payload = state_payload(state, state_path=default_state_path())
        if json_output:
            echo_json(payload)
        else:
            click.echo(state.default_cwd)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command()
@click.argument("target", required=False)
@click.option("--limit", type=click.IntRange(1, 10_000), default=DEFAULT_LIMIT, show_default=True)
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def stat(target: str, limit: int, timeout: float, json_output: bool) -> None:
    """Stat a Modal Volume root, file, or directory path."""
    try:
        parsed = resolve_target(target)
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
@click.argument("target", required=False)
@click.option(
    "--lines", "line_range", metavar="START:END", help="Read a bounded 1-based line range."
)
@click.option("--bytes", "byte_range", metavar="START:LEN", help="Read a bounded byte range.")
@click.option("--max-bytes", type=click.IntRange(1), default=DEFAULT_MAX_BYTES, show_default=True)
@click.option("--refresh", is_flag=True, help="Force a live read; cat is live by default.")
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def cat(
    target: str | None,
    line_range: str | None,
    byte_range: str | None,
    max_bytes: int,
    refresh: bool,
    timeout: float,
    json_output: bool,
) -> None:
    """Read a bounded byte slice from a remote file."""
    try:
        parsed = resolve_target(target)
        start, length = _parse_byte_range(byte_range, max_bytes=max_bytes)
        adapter = ModalAdapter(timeout=timeout)
        result = asyncio.run(
            adapter.cat_bytes(parsed, start=start, length=length, max_bytes=max_bytes)
        )
        if line_range is not None:
            line_start, line_end = _parse_line_range(line_range)
            result = _slice_cat_lines(result, line_start=line_start, line_end=line_end)
        if json_output:
            if refresh:
                payload = to_jsonable(result)
                payload["refresh"] = True
                echo_json(payload)
                return
            echo_json(result)
            return
        if result.encoding == "base64":
            data = base64.b64decode(result.content)
        else:
            data = result.content.encode("utf-8")
        click.get_binary_stream("stdout").write(data)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command()
@click.argument("target", required=False)
@click.option("--depth", type=click.IntRange(0), default=DEFAULT_DU_DEPTH, show_default=True)
@click.option("--limit", type=click.IntRange(1, 100_000), default=DEFAULT_LIMIT, show_default=True)
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def tree(target: str | None, depth: int, limit: int, timeout: float, json_output: bool) -> None:
    """List a bounded recursive tree."""
    try:
        parsed = resolve_target(target)
        payload = asyncio.run(_tree_target(parsed, depth=depth, limit=limit, timeout=timeout))
        if json_output:
            echo_json(payload)
        else:
            for entry in payload["entries"]:
                click.echo(f"{'  ' * int(entry['depth'])}{entry['type']}\t{entry['path']}")
            if payload["partial"]:
                click.echo(f"partial: limited by {payload['limited_by']}")
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command()
@click.argument("target", required=False)
@click.option("-s", "--summarize", is_flag=True, help="Summarize the target.")
@click.option("-h", "--human-readable", is_flag=True, help="Print human-readable sizes.")
@click.option("--depth", type=click.IntRange(0), default=DEFAULT_DU_DEPTH, show_default=True)
@click.option(
    "--limit", type=click.IntRange(1, 100_000), default=DEFAULT_DU_LIMIT, show_default=True
)
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def du(
    target: str | None,
    summarize: bool,
    human_readable: bool,
    depth: int,
    limit: int,
    timeout: float,
    json_output: bool,
) -> None:
    """Summarize remote file sizes with traversal budgets."""
    try:
        parsed = resolve_target(target)
        payload = asyncio.run(_du_target(parsed, depth=depth, limit=limit, timeout=timeout))
        payload["summarize"] = summarize
        if json_output:
            echo_json(payload)
        else:
            size = payload["human_size"] if human_readable else str(payload["size_bytes"])
            marker = " (partial)" if payload["partial"] else ""
            click.echo(f"{size}\t{payload['uri']}{marker}")
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command(name="index")
@click.argument("target", required=False)
@click.option("--store", "store_path", type=click.Path(path_type=str), help="SQLite store path.")
@click.option("--max-bytes", type=click.IntRange(1), default=DEFAULT_MAX_BYTES, show_default=True)
@click.option(
    "--limit", type=click.IntRange(1, 100_000), default=DEFAULT_DU_LIMIT, show_default=True
)
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def index_command(
    target: str | None,
    store_path: str | None,
    max_bytes: int,
    limit: int,
    timeout: float,
    json_output: bool,
) -> None:
    """Refresh sidecar metadata and bounded text chunks."""
    try:
        parsed = resolve_target(target)
        payload = asyncio.run(
            _index_target(
                parsed,
                store=IndexStore(store_path),
                max_bytes=max_bytes,
                limit=limit,
                timeout=timeout,
            )
        )
        if json_output:
            echo_json(payload)
        else:
            click.echo(f"indexed {payload['indexed_files']} files into {payload['store_path']}")
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command()
@click.argument("target", required=False)
@click.option("--store", "store_path", type=click.Path(path_type=str), help="SQLite store path.")
@click.option("--max-bytes", type=click.IntRange(1), default=DEFAULT_MAX_BYTES, show_default=True)
@click.option(
    "--limit", type=click.IntRange(1, 100_000), default=DEFAULT_DU_LIMIT, show_default=True
)
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def update(
    target: str | None,
    store_path: str | None,
    max_bytes: int,
    limit: int,
    timeout: float,
    json_output: bool,
) -> None:
    """Alias for index refresh."""
    index_command.callback(target, store_path, max_bytes, limit, timeout, json_output)  # type: ignore[attr-defined]


@main.command(name="find")
@click.argument("target", required=False)
@click.option("--glob", "glob_pattern", required=True, help="Path glob to match.")
@click.option("--size", "size_expr", help="Filter by size expression, e.g. >1024.")
@click.option("--mtime", "mtime_expr", help="Filter by integer mtime expression.")
@click.option("--store", "store_path", type=click.Path(path_type=str), help="SQLite store path.")
@click.option(
    "--limit", type=click.IntRange(1, 100_000), default=DEFAULT_DU_LIMIT, show_default=True
)
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def find_command(
    target: str | None,
    glob_pattern: str,
    size_expr: str | None,
    mtime_expr: str | None,
    store_path: str | None,
    limit: int,
    timeout: float,
    json_output: bool,
) -> None:
    """Find live remote metadata by path glob and simple predicates."""
    try:
        parsed = resolve_target(target)
        payload = asyncio.run(
            _find_target(
                parsed,
                glob_pattern=glob_pattern,
                size_expr=size_expr,
                mtime_expr=mtime_expr,
                store=IndexStore(store_path),
                limit=limit,
                timeout=timeout,
            )
        )
        if json_output:
            echo_json(payload)
        else:
            _print_entries(payload["entries"])
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command()
@click.argument("target", required=False)
@click.argument("pattern")
@click.option("--glob", "glob_pattern", help="Path glob to filter indexed chunks.")
@click.option("--context", type=click.IntRange(0), default=0, show_default=True)
@click.option("--store", "store_path", type=click.Path(path_type=str), help="SQLite store path.")
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def grep(
    target: str | None,
    pattern: str,
    glob_pattern: str | None,
    context: int,
    store_path: str | None,
    json_output: bool,
) -> None:
    """Grep cached text chunks from the sidecar index."""
    try:
        parsed = resolve_target(target)
        _require_indexable_target(parsed)
        store = IndexStore(store_path)
        matches = store.grep(
            parsed.volume_uri,
            prefix=parsed.path,
            pattern=pattern,
            glob=glob_pattern,
            context=context,
        )
        payload = {
            "uri": parsed.canonical_uri,
            "store_path": str(store.path),
            "pattern": pattern,
            "glob": glob_pattern,
            "match_count": len(matches),
            "matches": matches,
            "source": "indexed",
        }
        if json_output:
            echo_json(payload)
        else:
            for match in matches:
                click.echo(f"{match['path']}:{match['line']}:{match['text']}")
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command()
@click.argument("target", required=False)
@click.argument("query")
@click.option("--lex", is_flag=True, help="Use SQLite FTS5 lexical search.")
@click.option("--store", "store_path", type=click.Path(path_type=str), help="SQLite store path.")
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def search(
    target: str | None, query: str, lex: bool, store_path: str | None, json_output: bool
) -> None:
    """Search cached text chunks."""
    try:
        if not lex:
            raise MfsError(
                code="UNSUPPORTED_SEARCH_MODE",
                message="MVP search supports only --lex lexical search",
                retryable=False,
            )
        parsed = resolve_target(target)
        _require_indexable_target(parsed)
        store = IndexStore(store_path)
        results = store.search_lex(parsed.volume_uri, prefix=parsed.path, query=query)
        payload = {
            "uri": parsed.canonical_uri,
            "store_path": str(store.path),
            "query": query,
            "mode": "lex",
            "result_count": len(results),
            "results": results,
            "source": "indexed",
        }
        if json_output:
            echo_json(payload)
        else:
            for result in results:
                click.echo(f"{result['path']}\t{result['snippet']}")
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command()
@click.argument("target", required=False)
@click.option("--jsonl", is_flag=True, help="Print manifest rows as JSONL.")
@click.option(
    "--limit", type=click.IntRange(1, 100_000), default=DEFAULT_DU_LIMIT, show_default=True
)
@click.option("--timeout", type=float, default=30.0, show_default=True)
def manifest(target: str | None, jsonl: bool, limit: int, timeout: float) -> None:
    """Produce a live metadata manifest."""
    try:
        parsed = resolve_target(target)
        rows = asyncio.run(_manifest_rows(parsed, limit=limit, timeout=timeout))
        if jsonl:
            for row in rows:
                click.echo(json.dumps(row, sort_keys=True))
        else:
            echo_json({"uri": parsed.canonical_uri, "count": len(rows), "entries": rows})
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=False)


@main.command()
@click.argument("target", required=False)
@click.option("--since", "since_path", required=True, type=click.Path(path_type=str))
@click.option(
    "--limit", type=click.IntRange(1, 100_000), default=DEFAULT_DU_LIMIT, show_default=True
)
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def changed(
    target: str | None,
    since_path: str,
    limit: int,
    timeout: float,
    json_output: bool,
) -> None:
    """Compare live metadata against a manifest or index."""
    try:
        parsed = resolve_target(target)
        _require_indexable_target(parsed)
        live_rows = asyncio.run(_manifest_rows(parsed, limit=limit, timeout=timeout))
        since_rows = _load_since_rows(since_path, volume_uri=parsed.volume_uri)
        payload = _changed_payload(parsed, live_rows=live_rows, since_rows=since_rows)
        if json_output:
            echo_json(payload)
        else:
            click.echo(
                f"added={payload['added_count']} removed={payload['removed_count']} "
                f"modified={payload['modified_count']}"
            )
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command(name="get")
@click.argument("target")
@click.argument("local_dest", type=click.Path(path_type=str))
@click.option("--recursive", is_flag=True, help="Download a directory recursively.")
@click.option("--force", is_flag=True, help="Overwrite existing local paths.")
@click.option(
    "--limit", type=click.IntRange(1, 100_000), default=DEFAULT_DU_LIMIT, show_default=True
)
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def get_command(
    target: str,
    local_dest: str,
    recursive: bool,
    force: bool,
    limit: int,
    timeout: float,
    json_output: bool,
) -> None:
    """Download a remote file or explicit recursive directory."""
    try:
        parsed = resolve_target(target)
        adapter = ModalAdapter(timeout=timeout)
        payload = asyncio.run(
            adapter.get_path(
                parsed,
                local_dest=Path(local_dest),
                recursive=recursive,
                force=force,
                limit=limit,
            )
        )
        if json_output:
            echo_json(payload)
        else:
            click.echo(f"downloaded {payload['source_uri']} -> {payload['local_dest']}")
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command(name="put")
@click.argument("local_path", type=click.Path(path_type=str))
@click.argument("target")
@click.option("--recursive", is_flag=True, help="Upload a directory recursively.")
@click.option("--force", is_flag=True, help="Overwrite existing remote paths.")
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def put_command(
    local_path: str,
    target: str,
    recursive: bool,
    force: bool,
    timeout: float,
    json_output: bool,
) -> None:
    """Upload a local file or explicit recursive directory."""
    try:
        source = Path(local_path)
        if not source.exists():
            raise MfsError(
                code="LOCAL_NOT_FOUND",
                message="Local source path does not exist",
                uri=str(source),
                retryable=False,
            )
        if source.is_dir() and not recursive:
            raise MfsError(
                code="RECURSIVE_REQUIRED",
                message="put requires --recursive when LOCAL_PATH is a directory",
                uri=str(source),
                retryable=False,
            )
        parsed = resolve_target(target)
        adapter = ModalAdapter(timeout=timeout)
        if not force and asyncio.run(adapter.path_exists(parsed)):
            raise MfsError(
                code="REMOTE_DEST_EXISTS",
                message="Remote destination already exists; pass --force to overwrite",
                uri=parsed.canonical_uri,
                retryable=False,
            )
        payload = asyncio.run(adapter.put_path(source, parsed, recursive=recursive, force=force))
        if json_output:
            echo_json(payload)
        else:
            click.echo(f"uploaded {payload['source_path']} -> {payload['target_uri']}")
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command(name="rm")
@click.argument("target")
@click.option("-r", "--recursive", is_flag=True, help="Remove recursively.")
@click.option("--yes", is_flag=True, help="Confirm destructive removal.")
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def rm_command(target: str, recursive: bool, yes: bool, timeout: float, json_output: bool) -> None:
    """Remove a remote file or explicit recursive directory."""
    try:
        parsed = resolve_target(target)
        if not yes:
            raise _confirmation_required("rm", parsed.canonical_uri)
        payload = asyncio.run(
            ModalAdapter(timeout=timeout).remove_path(parsed, recursive=recursive)
        )
        if json_output:
            echo_json(payload)
        else:
            click.echo(f"removed {payload['target_uri']}")
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command(name="cp")
@click.argument("source")
@click.argument("target")
@click.option("--recursive", is_flag=True, help="Copy recursively.")
@click.option("--force", is_flag=True, help="Overwrite existing remote paths.")
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def cp_command(
    source: str,
    target: str,
    recursive: bool,
    force: bool,
    timeout: float,
    json_output: bool,
) -> None:
    """Copy within the same Modal profile/environment/volume."""
    try:
        source_parsed = resolve_target(source)
        target_parsed = resolve_target(target)
        _require_same_volume(source_parsed, target_parsed)
        adapter = ModalAdapter(timeout=timeout)
        if not force and asyncio.run(adapter.path_exists(target_parsed)):
            raise MfsError(
                code="REMOTE_DEST_EXISTS",
                message="Remote destination already exists; pass --force to overwrite",
                uri=target_parsed.canonical_uri,
                retryable=False,
            )
        payload = asyncio.run(adapter.copy_path(source_parsed, target_parsed, recursive=recursive))
        payload["overwrote"] = force
        if json_output:
            echo_json(payload)
        else:
            click.echo(f"copied {payload['source_uri']} -> {payload['target_uri']}")
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command(name="mv")
@click.argument("source")
@click.argument("target")
@click.option("--force", is_flag=True, help="Overwrite existing remote paths.")
@click.option("--yes", is_flag=True, help="Confirm destructive source removal.")
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def mv_command(
    source: str,
    target: str,
    force: bool,
    yes: bool,
    timeout: float,
    json_output: bool,
) -> None:
    """Move within the same Modal profile/environment/volume via copy then remove."""
    try:
        source_parsed = resolve_target(source)
        target_parsed = resolve_target(target)
        _require_same_volume(source_parsed, target_parsed)
        if not yes:
            raise _confirmation_required("mv", source_parsed.canonical_uri)
        if source_parsed.path == target_parsed.path or target_parsed.path.startswith(
            source_parsed.path.rstrip("/") + "/"
        ):
            raise MfsError(
                code="INVALID_TARGET",
                message="mv target must not be the same path or inside the source path",
                uri=target_parsed.canonical_uri,
                retryable=False,
            )
        adapter = ModalAdapter(timeout=timeout)
        if not force and asyncio.run(adapter.path_exists(target_parsed)):
            raise MfsError(
                code="REMOTE_DEST_EXISTS",
                message="Remote destination already exists; pass --force to overwrite",
                uri=target_parsed.canonical_uri,
                retryable=False,
            )
        copy_payload = asyncio.run(adapter.copy_path(source_parsed, target_parsed, recursive=True))
        remove_payload = asyncio.run(adapter.remove_path(source_parsed, recursive=True))
        payload = {
            "operation": "mv",
            "source_uri": source_parsed.canonical_uri,
            "target_uri": target_parsed.canonical_uri,
            "overwrote": force,
            "confirmed_by_flag": True,
            "copy": copy_payload,
            "remove": remove_payload,
        }
        if json_output:
            echo_json(payload)
        else:
            click.echo(f"moved {payload['source_uri']} -> {payload['target_uri']}")
    except Exception as exc:  # noqa: BLE001
        handle_error(exc, json_output=json_output)


@main.command(name="mkdir")
@click.argument("target")
@click.option("--parents", is_flag=True, help="Create parent directories when supported.")
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON.")
def mkdir_command(target: str, parents: bool, timeout: float, json_output: bool) -> None:
    """Create a remote directory-like target."""
    try:
        parsed = resolve_target(target)
        payload = asyncio.run(ModalAdapter(timeout=timeout).mkdir_path(parsed, parents=parents))
        if json_output:
            echo_json(payload)
        else:
            click.echo(f"created {payload['target_uri']}")
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


async def _tree_target(
    parsed: ParsedTarget,
    *,
    depth: int,
    limit: int,
    timeout: float,
) -> dict[str, Any]:
    if parsed.kind != "modal_path":
        payload = await _list_target(parsed, recursive=False, limit=limit, timeout=timeout)
        payload["depth"] = depth
        payload["partial"] = False
        payload["limited_by"] = None
        return payload
    adapter = ModalAdapter(timeout=timeout)
    entries = await adapter.list_files(parsed, recursive=True, limit=limit)
    visible_entries, depth_limited = _entries_with_depth(
        entries, root_path=parsed.path, max_depth=depth
    )
    return {
        "target": _target_payload(parsed),
        "uri": parsed.canonical_uri,
        "depth": depth,
        "limit": limit,
        "count": len(visible_entries),
        "entry_count": len(entries),
        "partial": depth_limited or len(entries) >= limit,
        "limited_by": "depth"
        if depth_limited
        else ("entry_limit" if len(entries) >= limit else None),
        "entries": visible_entries,
    }


async def _du_target(
    parsed: ParsedTarget,
    *,
    depth: int,
    limit: int,
    timeout: float,
) -> dict[str, Any]:
    if parsed.kind != "modal_path":
        return {
            "target": _target_payload(parsed),
            "uri": parsed.raw,
            "size_bytes": 0,
            "human_size": _human_size(0),
            "partial": False,
            "entry_count": 0,
            "limit": limit,
            "depth": depth,
            "limited_by": None,
            "source": "live",
        }
    adapter = ModalAdapter(timeout=timeout)
    entries = await adapter.list_files(parsed, recursive=True, limit=limit)
    visible_entries, depth_limited = _entries_with_depth(
        entries, root_path=parsed.path, max_depth=depth
    )
    size_bytes = sum(
        int(entry.get("size") or 0) for entry in visible_entries if entry.get("type") == "file"
    )
    return {
        "target": _target_payload(parsed),
        "uri": parsed.canonical_uri,
        "size_bytes": size_bytes,
        "human_size": _human_size(size_bytes),
        "partial": depth_limited or len(entries) >= limit,
        "entry_count": len(entries),
        "limit": limit,
        "depth": depth,
        "limited_by": "depth"
        if depth_limited
        else ("entry_limit" if len(entries) >= limit else None),
        "source": "live",
    }


async def _index_target(
    parsed: ParsedTarget,
    *,
    store: IndexStore,
    max_bytes: int,
    limit: int,
    timeout: float,
) -> dict[str, Any]:
    _require_indexable_target(parsed)
    store.ensure_schema()
    store.upsert_volume(
        canonical_uri=parsed.volume_uri,
        profile=parsed.profile or "",
        environment=parsed.environment or "",
        name=parsed.volume or "",
    )
    adapter = ModalAdapter(timeout=timeout)
    entries = await adapter.list_files(parsed, recursive=True, limit=limit)
    indexed_files = 0
    skipped_files = 0
    for entry in entries:
        payload = _entry_payload(entry)
        store.upsert_file(parsed.volume_uri, payload)
        if payload.get("type") != "file":
            continue
        path = str(payload.get("path") or "/")
        skip_reason = _text_skip_reason(path, payload.get("size"), max_bytes=max_bytes)
        if skip_reason:
            store.mark_skipped(parsed.volume_uri, path, skip_reason)
            skipped_files += 1
            continue
        try:
            file_target = parse_target(f"{parsed.volume_uri}{path if path != '/' else ''}")
            result = await adapter.cat_bytes(
                file_target, start=0, length=max_bytes, max_bytes=max_bytes
            )
        except MfsError as exc:
            store.mark_skipped(parsed.volume_uri, path, exc.code.lower())
            skipped_files += 1
            continue
        if result.encoding != "utf-8" or "\x00" in result.content:
            store.mark_skipped(parsed.volume_uri, path, "binary")
            skipped_files += 1
            continue
        store.replace_chunks(parsed.volume_uri, path, _chunk_text(result.content))
        indexed_files += 1
    return {
        "uri": parsed.canonical_uri,
        "store_path": str(store.path),
        "max_bytes": max_bytes,
        "limit": limit,
        "entry_count": len(entries),
        "indexed_files": indexed_files,
        "skipped_files": skipped_files,
        "partial": len(entries) >= limit,
        "source": "live",
    }


async def _find_target(
    parsed: ParsedTarget,
    *,
    glob_pattern: str,
    size_expr: str | None,
    mtime_expr: str | None,
    store: IndexStore,
    limit: int,
    timeout: float,
) -> dict[str, Any]:
    _require_indexable_target(parsed)
    store.ensure_schema()
    adapter = ModalAdapter(timeout=timeout)
    entries = await adapter.list_files(parsed, recursive=True, limit=limit)
    matches = []
    for entry in entries:
        payload = _entry_payload(entry)
        store.upsert_file(parsed.volume_uri, payload)
        path = str(payload.get("path") or "")
        if not fnmatch.fnmatch(path.lstrip("/"), glob_pattern) and not fnmatch.fnmatch(
            path, glob_pattern
        ):
            continue
        if size_expr and not _matches_numeric_expr(payload.get("size"), size_expr):
            continue
        if mtime_expr and not _matches_numeric_expr(payload.get("mtime"), mtime_expr):
            continue
        matches.append(payload)
    return {
        "uri": parsed.canonical_uri,
        "store_path": str(store.path),
        "glob": glob_pattern,
        "size": size_expr,
        "mtime": mtime_expr,
        "limit": limit,
        "count": len(matches),
        "partial": len(entries) >= limit,
        "source": "live",
        "entries": matches,
    }


async def _manifest_rows(
    parsed: ParsedTarget, *, limit: int, timeout: float
) -> list[dict[str, Any]]:
    _require_indexable_target(parsed)
    adapter = ModalAdapter(timeout=timeout)
    entries = await adapter.list_files(parsed, recursive=True, limit=limit)
    rows = []
    for entry in entries:
        payload = _entry_payload(entry)
        payload["volume_uri"] = parsed.volume_uri
        payload["remote_seen_at"] = utc_now_iso()
        rows.append(payload)
    return rows


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


def _filter_hidden(entries: list[Any], *, include_hidden: bool) -> list[Any]:
    if include_hidden:
        return entries
    return [entry for entry in entries if not _entry_name(entry).startswith(".")]


def _entry_name(entry: Any) -> str:
    if isinstance(entry, dict):
        name = entry.get("name") or entry.get("path") or ""
    else:
        name = getattr(entry, "name", "") or getattr(entry, "path", "")
    return str(name).rstrip("/").split("/")[-1]


def _print_entries(entries: list[Any], *, long_format: bool = False) -> None:
    for entry in entries:
        if isinstance(entry, dict):
            type_label = entry.get("type", "")
            name = entry.get("name") or entry.get("path") or ""
            size = entry.get("size", "")
            mtime = entry.get("mtime", "")
        else:
            type_label = getattr(entry, "type", "")
            name = getattr(entry, "name", "") or getattr(entry, "path", "")
            size = getattr(entry, "size", "") or ""
            mtime = getattr(entry, "mtime", "") or ""
        if long_format:
            click.echo(f"{type_label}\t{size}\t{mtime}\t{name}")
        else:
            click.echo(f"{type_label}\t{size}\t{name}")


def _cwd_value(parsed: ParsedTarget) -> str:
    if parsed.kind == "modal_path":
        return parsed.canonical_uri
    if parsed.kind == "providers_root":
        return "Volumes/"
    return parsed.raw.rstrip("/")


def _entries_with_depth(
    entries: list[Any], *, root_path: str, max_depth: int
) -> tuple[list[dict[str, Any]], bool]:
    visible_entries: list[dict[str, Any]] = []
    depth_limited = False
    root_parts = [part for part in root_path.split("/") if part]
    for entry in entries:
        payload = _entry_payload(entry)
        path = str(payload.get("path") or "/")
        entry_parts = [part for part in path.split("/") if part]
        if root_parts and entry_parts[: len(root_parts)] == root_parts:
            relative_parts = entry_parts[len(root_parts) :]
        else:
            relative_parts = entry_parts
        entry_depth = max(len(relative_parts) - 1, 0)
        if entry_depth > max_depth:
            depth_limited = True
            continue
        payload["depth"] = entry_depth
        visible_entries.append(payload)
    return visible_entries, depth_limited


def _entry_payload(entry: Any) -> dict[str, Any]:
    if isinstance(entry, dict):
        return dict(entry)
    return {
        "path": getattr(entry, "path", None),
        "name": getattr(entry, "name", None),
        "type": getattr(entry, "type", None),
        "size": getattr(entry, "size", None),
        "mtime": getattr(entry, "mtime", None),
    }


def _human_size(size_bytes: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(size_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024


def _require_indexable_target(parsed: ParsedTarget) -> None:
    if parsed.kind != "modal_path":
        raise MfsError(
            code="INVALID_TARGET",
            message="Command requires a concrete Modal Volume target",
            uri=parsed.raw,
            retryable=False,
        )


def _confirmation_required(operation: str, uri: str) -> MfsError:
    return MfsError(
        code="CONFIRMATION_REQUIRED",
        message=f"{operation} requires explicit confirmation with --yes",
        uri=uri,
        retryable=False,
        details={"operation": operation},
    )


def _require_same_volume(source: ParsedTarget, target: ParsedTarget) -> None:
    _require_indexable_target(source)
    _require_indexable_target(target)
    source_key = (source.profile, source.environment, source.volume)
    target_key = (target.profile, target.environment, target.volume)
    if source_key != target_key:
        raise MfsError(
            code="CROSS_VOLUME_UNSUPPORTED",
            message="MVP cp/mv supports only paths in the same profile/environment/volume",
            uri=source.canonical_uri,
            retryable=False,
            details={"target_uri": target.canonical_uri},
        )


def _text_skip_reason(path: str, size: Any, *, max_bytes: int) -> str | None:
    lowered = path.lower()
    name = lowered.rsplit("/", 1)[-1]
    if name in {".env", ".env.local"} or any(token in name for token in ["secret", "token"]):
        return "likely_secret"
    if lowered.endswith((".pem", ".key", ".p12", ".zip", ".gz", ".parquet", ".safetensors")):
        return "unsupported"
    if size is not None and int(size) > max_bytes:
        return "too_large"
    return None


def _chunk_text(text: str, *, max_chars: int = 32_000) -> list[str]:
    if not text:
        return [""]
    return [text[index : index + max_chars] for index in range(0, len(text), max_chars)]


def _matches_numeric_expr(value: Any, expr: str) -> bool:
    if value is None:
        return False
    match = re.fullmatch(r"\s*(>=|<=|>|<|=)?\s*(\d+)\s*", expr)
    if not match:
        raise MfsError(
            code="INVALID_FILTER",
            message=f"Invalid numeric filter expression: {expr}",
            retryable=False,
        )
    op = match.group(1) or "="
    expected = int(match.group(2))
    actual = int(value)
    return {
        ">": actual > expected,
        ">=": actual >= expected,
        "<": actual < expected,
        "<=": actual <= expected,
        "=": actual == expected,
    }[op]


def _load_since_rows(path_text: str, *, volume_uri: str) -> list[dict[str, Any]]:
    path = Path(path_text).expanduser()
    if str(path).endswith((".sqlite", ".db")):
        return list(IndexStore(path).files_by_path(volume_uri).values())
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _changed_payload(
    parsed: ParsedTarget, *, live_rows: list[dict[str, Any]], since_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    live = {str(row.get("path")): row for row in live_rows}
    since = {str(row.get("path")): row for row in since_rows}
    added = [live[path] for path in sorted(live.keys() - since.keys())]
    removed = [since[path] for path in sorted(since.keys() - live.keys())]
    modified = [
        live[path]
        for path in sorted(live.keys() & since.keys())
        if _metadata_fingerprint(live[path]) != _metadata_fingerprint(since[path])
    ]
    return {
        "uri": parsed.canonical_uri,
        "added_count": len(added),
        "removed_count": len(removed),
        "modified_count": len(modified),
        "added": added,
        "removed": removed,
        "modified": modified,
    }


def _metadata_fingerprint(row: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (row.get("type"), row.get("size"), row.get("mtime"))


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


def _parse_line_range(line_range: str) -> tuple[int, int]:
    try:
        start_text, end_text = line_range.split(":", 1)
        start = int(start_text)
        end = int(end_text)
    except ValueError as exc:
        raise MfsError(
            code="INVALID_LINE_RANGE",
            message="--lines must use START:END with positive 1-based integers",
            retryable=False,
        ) from exc
    if start < 1 or end < start:
        raise MfsError(
            code="INVALID_LINE_RANGE",
            message="--lines START must be >= 1 and END must be >= START",
            retryable=False,
        )
    return start, end


def _slice_cat_lines(result: Any, *, line_start: int, line_end: int) -> dict[str, Any]:
    if result.encoding != "utf-8":
        raise MfsError(
            code="TEXT_DECODE_ERROR",
            message="--lines requires UTF-8 text content",
            uri=result.uri,
            retryable=False,
        )
    lines = result.content.splitlines()
    selected = lines[line_start - 1 : line_end]
    payload = {
        "uri": result.uri,
        "path": result.path,
        "line_start": line_start,
        "line_end": line_end,
        "max_bytes": result.requested_len,
        "downloaded_len": result.downloaded_len,
        "truncated": result.truncated,
        "encoding": "utf-8",
        "content": "\n".join(selected),
        "read_at": result.read_at,
    }
    return payload


if __name__ == "__main__":
    main()

"""SQLite sidecar index and lexical search helpers."""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from mfs.output import utc_now_iso

DEFAULT_STORE_ENV_VAR = "MFS_STORE_PATH"


def default_store_path() -> Path:
    override = os.environ.get(DEFAULT_STORE_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "mfs" / "index.sqlite"


class IndexStore:
    """Small SQLite wrapper for mfs metadata and FTS chunks."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path is not None else default_store_path()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                create table if not exists volumes (
                  canonical_uri text primary key,
                  profile text not null default '',
                  environment text not null default '',
                  name text not null default '',
                  volume_id text,
                  volume_version integer,
                  workspace_id text,
                  workspace_name text,
                  seen_at text not null
                );

                create table if not exists files (
                  volume_uri text not null,
                  volume_id text,
                  path text not null,
                  type text not null,
                  size integer,
                  mtime integer,
                  sha256 text,
                  mime text,
                  ext text,
                  cache_state text not null default 'metadata_only',
                  skip_reason text,
                  remote_seen_at text not null,
                  indexed_at text,
                  primary key (volume_uri, path)
                );

                create table if not exists chunks (
                  volume_uri text not null,
                  path text not null,
                  chunk_id integer not null,
                  start_byte integer,
                  end_byte integer,
                  start_line integer,
                  end_line integer,
                  text text,
                  primary key (volume_uri, path, chunk_id)
                );

                create virtual table if not exists chunks_fts using fts5(
                  text,
                  volume_uri unindexed,
                  path unindexed,
                  chunk_id unindexed,
                  tokenize = 'unicode61'
                );
                """
            )

    def upsert_volume(
        self,
        *,
        canonical_uri: str,
        profile: str = "",
        environment: str = "",
        name: str = "",
        volume_id: str | None = None,
        volume_version: int | None = None,
    ) -> None:
        self.ensure_schema()
        with self.connect() as conn:
            conn.execute(
                """
                insert into volumes (
                  canonical_uri, profile, environment, name, volume_id, volume_version, seen_at
                )
                values (?, ?, ?, ?, ?, ?, ?)
                on conflict(canonical_uri) do update set
                  profile = excluded.profile,
                  environment = excluded.environment,
                  name = excluded.name,
                  volume_id = excluded.volume_id,
                  volume_version = excluded.volume_version,
                  seen_at = excluded.seen_at
                """,
                (
                    canonical_uri,
                    profile,
                    environment,
                    name,
                    volume_id,
                    volume_version,
                    utc_now_iso(),
                ),
            )

    def upsert_file(self, volume_uri: str, entry: dict[str, Any]) -> None:
        self.ensure_schema()
        path = str(entry.get("path") or "/")
        ext = Path(path).suffix.lower() or None
        with self.connect() as conn:
            conn.execute(
                """
                insert into files (
                  volume_uri, path, type, size, mtime, ext, cache_state, skip_reason, remote_seen_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(volume_uri, path) do update set
                  type = excluded.type,
                  size = excluded.size,
                  mtime = excluded.mtime,
                  ext = excluded.ext,
                  remote_seen_at = excluded.remote_seen_at
                """,
                (
                    volume_uri,
                    path,
                    str(entry.get("type") or "unknown"),
                    entry.get("size"),
                    entry.get("mtime"),
                    ext,
                    entry.get("cache_state") or "metadata_only",
                    entry.get("skip_reason"),
                    utc_now_iso(),
                ),
            )

    def mark_skipped(self, volume_uri: str, path: str, reason: str) -> None:
        self.ensure_schema()
        with self.connect() as conn:
            conn.execute(
                """
                update files
                set cache_state = 'skipped', skip_reason = ?, indexed_at = ?
                where volume_uri = ? and path = ?
                """,
                (reason, utc_now_iso(), volume_uri, path),
            )

    def replace_chunks(self, volume_uri: str, path: str, texts: list[str]) -> None:
        self.ensure_schema()
        indexed_at = utc_now_iso()
        with self.connect() as conn:
            conn.execute("delete from chunks where volume_uri = ? and path = ?", (volume_uri, path))
            conn.execute(
                "delete from chunks_fts where volume_uri = ? and path = ?", (volume_uri, path)
            )
            start_line = 1
            for chunk_id, text in enumerate(texts):
                line_count = max(len(text.splitlines()), 1)
                end_line = start_line + line_count - 1
                encoded_len = len(text.encode("utf-8"))
                conn.execute(
                    """
                    insert into chunks (
                      volume_uri, path, chunk_id, start_byte, end_byte, start_line, end_line, text
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (volume_uri, path, chunk_id, 0, encoded_len, start_line, end_line, text),
                )
                conn.execute(
                    """
                    insert into chunks_fts (text, volume_uri, path, chunk_id)
                    values (?, ?, ?, ?)
                    """,
                    (text, volume_uri, path, chunk_id),
                )
                start_line = end_line + 1
            conn.execute(
                """
                update files
                set cache_state = 'text_indexed', skip_reason = null, indexed_at = ?
                where volume_uri = ? and path = ?
                """,
                (indexed_at, volume_uri, path),
            )

    def files(self, volume_uri: str, *, prefix: str = "/") -> list[dict[str, Any]]:
        self.ensure_schema()
        exact_path = _normalize_path(prefix)
        like_prefix = exact_path.rstrip("/") + "/%"
        with self.connect() as conn:
            rows = conn.execute(
                """
                select * from files
                where volume_uri = ? and (path = ? or path like ?)
                order by path
                """,
                (volume_uri, exact_path, like_prefix),
            ).fetchall()
        return [dict(row) for row in rows]

    def grep(
        self,
        volume_uri: str,
        *,
        prefix: str,
        pattern: str,
        glob: str | None = None,
        context: int = 0,
    ) -> list[dict[str, Any]]:
        self.ensure_schema()
        regex = re.compile(pattern)
        matches: list[dict[str, Any]] = []
        with self.connect() as conn:
            rows = conn.execute(
                """
                select volume_uri, path, chunk_id, start_line, text from chunks
                where volume_uri = ? and (path = ? or path like ?)
                order by path, chunk_id
                """,
                (volume_uri, _normalize_path(prefix), _normalize_path(prefix).rstrip("/") + "/%"),
            ).fetchall()
        for row in rows:
            path = str(row["path"])
            if glob and not Path(path).match(glob):
                continue
            lines = str(row["text"] or "").splitlines()
            for offset, line in enumerate(lines):
                if regex.search(line):
                    line_number = int(row["start_line"] or 1) + offset
                    start = max(offset - context, 0)
                    end = min(offset + context + 1, len(lines))
                    matches.append(
                        {
                            "volume_uri": row["volume_uri"],
                            "path": path,
                            "chunk_id": row["chunk_id"],
                            "line": line_number,
                            "text": line,
                            "context": lines[start:end],
                        }
                    )
        return matches

    def search_lex(self, volume_uri: str, *, prefix: str, query: str) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self.connect() as conn:
            rows = conn.execute(
                """
                select volume_uri, path, chunk_id,
                       snippet(chunks_fts, 0, '[', ']', '...', 12) as snippet,
                       bm25(chunks_fts) as score
                from chunks_fts
                where chunks_fts match ?
                  and volume_uri = ?
                  and (path = ? or path like ?)
                order by score
                """,
                (
                    query,
                    volume_uri,
                    _normalize_path(prefix),
                    _normalize_path(prefix).rstrip("/") + "/%",
                ),
            ).fetchall()
        return [dict(row) for row in rows]

    def files_by_path(self, volume_uri: str) -> dict[str, dict[str, Any]]:
        self.ensure_schema()
        with self.connect() as conn:
            rows = conn.execute(
                "select * from files where volume_uri = ?", (volume_uri,)
            ).fetchall()
        return {str(row["path"]): dict(row) for row in rows}


def _normalize_path(path: str) -> str:
    stripped = path.strip("/")
    return f"/{stripped}" if stripped else "/"

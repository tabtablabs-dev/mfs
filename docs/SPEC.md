# mfs Spec

## Goal

Build a Modal Volume query CLI for agents: a filesystem-shaped command surface plus a local SQLite sidecar index that lets agents cheaply inspect, find, grep, manifest, and safely manipulate Modal Volumes while respecting Modal's remote, snapshot/commit/reload semantics.

`mfs` exists because Modal's native CLI is resource-oriented and awkward compared with a typical filesystem workflow. The design target is not POSIX compatibility; it is safe, bounded, machine-readable filesystem querying.

## Non-goals for MVP

- POSIX/FUSE/NFS mount.
- Bidirectional rsync clone.
- Multi-cloud storage abstraction.
- Semantic embeddings by default.
- Hidden background mutation of Modal state.

## Users

- AI agents needing reliable filesystem context from Modal Volumes.
- Human operators who want inspectable CLI commands and manifests.
- Modal users storing model artifacts, datasets, logs, generated outputs, and agent workspaces.

## Core use cases

1. Inspect remote tree without downloading it.
2. Find candidate files by glob, type, size, mtime, or path terms.
3. Read bounded slices of text files.
4. Grep/search cached/indexed text.
5. Produce manifests for audit/change detection.
6. Upload/download specific files or directories explicitly.
7. Delete/copy/move with guardrails.
8. Expose all above as JSON for agent tools/MCP.

## Modal adapter decision

Decision: `mfs` is SDK-first. It should use the Modal Python SDK for core operations rather than shelling out to `modal volume`.

Rationale:

- `mfs` is a Python Click CLI; the Modal SDK is the real API boundary.
- Wrapping `modal volume` would preserve the awkwardness and add subprocess/parsing fragility.
- SDK methods map well to core operations: volume lookup, listing, file reads, batched uploads, removal, and volume-internal copies.
- SDK-first makes structured JSON/error handling easier.
- CLI subprocess fallback should be limited to `doctor`/debug parity or SDK gaps.

Open adapter detail: exact profile plumbing must be verified. Modal's `Client.from_env()` path is singleton-like and profile-sensitive, so `mfs` must not reuse one active-profile client across different `PROFILE` path segments. Prefer a per-profile client factory/cache that reads the selected profile's token/server settings explicitly. If direct profile plumbing is unsafe or not public enough, isolate a `MODAL_PROFILE=<profile>` subprocess fallback inside the Modal adapter only.

Public SDK is the first choice. Adapter-confined private/proto calls are allowed only when needed for bounded agent semantics that public SDK does not expose, notably `VolumeGetFile2(start,len)` byte ranges and `VolumeListFiles2(max_entries)` bounded listings. `mfs doctor` must report which path is active.

## Proposed URI

```text
modal://PROFILE/ENV/VOLUME/path/to/file
```

Examples:

```text
modal://default/main/models/qwen/model.safetensors
modal://default/dev/agent-workspaces/run-123/trace.jsonl
```

Decision: `PROFILE` and `ENV` are required in MVP and must not silently default from Modal profile or environment state.

## Alternative remote-filesystem address

Instead of forcing URI syntax into every command, `mfs` can treat Modal Volumes like roots on a remote server:

```text
Volumes/modal/PROFILE/ENV/VOLUME/path/to/file
```

Examples:

```text
Volumes/modal/default/main/models/qwen/model.safetensors
Volumes/modal/default/dev/agent-workspaces/run-123/trace.jsonl
```

Pros:

- Feels like a normal filesystem path.
- Better matches the product promise: make Modal Volumes less awkward for filesystem workflows.
- Easy for agents to compose with existing path-oriented tools and mental models.
- Leaves room for other providers later:

```text
Volumes/s3/BUCKET/path
Volumes/r2/ACCOUNT/BUCKET/path
Volumes/local/name/path
```

Cons:

- Looks like a relative local path unless reserved/documented clearly.
- Needs careful parsing so users do not expect it to exist on disk.
- Shell completion and error messages must explain that `Volumes/...` is a virtual path handled by `mfs`.

Resolution: use remote-filesystem paths as the primary CLI UX and keep `modal://PROFILE/ENV/VOLUME/path` as a canonical machine URI accepted everywhere. The profile and environment segments are required in both forms for MVP.

Primary examples:

```text
mfs ls Volumes/modal/default/main/models/
mfs cat Volumes/modal/default/main/models/config.json --lines 1:120
mfs put ./artifact.bin Volumes/modal/default/main/artifacts/artifact.bin
```

Machine/canonical examples:

```text
mfs ls modal://default/main/models/
mfs cat modal://default/main/models/config.json --lines 1:120
```

## MVP commands

```text
mfs ls URI [--json]
mfs tree URI [--depth N] [--limit N] [--json]
mfs stat URI [--json]
mfs cat URI [--bytes START:LEN] [--lines START:END] [--max-bytes N] [--refresh]
mfs get URI LOCAL_DEST [--recursive] [--force]
mfs put LOCAL_PATH URI [--recursive] [--force]
mfs rm URI [--recursive] --yes
mfs cp SRC_URI DST_URI [--recursive] [--force]  # MVP: same profile/env/volume only
mfs find URI --glob GLOB [--size EXPR] [--mtime EXPR] [--json]
mfs grep URI PATTERN [--glob GLOB] [--context N] [--json]
mfs search URI QUERY [--lex] [--json]
mfs index URI [--store PATH] [--max-bytes N]
mfs update URI [--store PATH]
mfs manifest URI [--jsonl]
mfs changed URI --since MANIFEST_OR_INDEX [--json]
mfs doctor URI [--json]
```

Root discovery is also MVP:

```text
mfs ls Volumes/
mfs ls Volumes/modal/
mfs ls Volumes/modal/PROFILE/
mfs ls Volumes/modal/PROFILE/ENV/
```

## Later commands

```text
mfs search URI QUERY [--semantic|--hybrid]
mfs sql SQL [--store PATH]
mfs diff URI_A URI_B
mfs mv SRC_URI DST_URI --yes
mfs sync LOCAL_DIR URI --dry-run
mfs mcp
```

## Output contract

Every command that returns structured data must support JSON. Errors should include:

```json
{
  "error": {
    "code": "REMOTE_NOT_FOUND",
    "message": "Path not found",
    "uri": "modal://default/main/vol/path",
    "retryable": false
  }
}
```

## Sidecar SQLite model

Decision: MVP index includes metadata, bounded text content cache, and SQLite FTS5 lexical search. Semantic/vector search is post-MVP.

This means `grep` and `search --lex` are MVP features, backed by cached text chunks. Indexing must skip or mark files that are too large, binary, likely secret-bearing, or otherwise unsafe to decode as text.

```sql
create table volumes (
  canonical_uri text primary key,
  profile text not null,
  environment text not null,
  name text not null,
  volume_id text,
  volume_version integer,
  workspace_id text,
  workspace_name text,
  seen_at text not null
);

create table files (
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

create table chunks (
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
```

FTS5 virtual table indexes `chunks.text` in MVP:

```sql
create virtual table chunks_fts using fts5(
  text,
  volume_uri unindexed,
  path unindexed,
  chunk_id unindexed,
  tokenize = 'unicode61'
);
```

The FTS table may be rebuilt from `chunks`; `chunks` remains the source table for line/byte ranges and cache metadata.

## Store and cache policy

Decision: hybrid store/cache policy.

Defaults:

```text
~/.cache/mfs/index.sqlite
~/.cache/mfs/content/
```

Every command that reads or writes the index accepts an explicit store path:

```text
--store .mfs/index.sqlite
```

Behavior:

- User-cache default keeps ordinary use from littering repositories.
- Repo-local `--store` supports reproducible agent runs and project-pinned indexes.
- JSON output for index/search/grep/find/changed must include `store_path`.
- Content cache should be colocated with the selected store unless overridden later.
- `.mfs/` is ignored by default in this repo, but users may intentionally commit manifests, not caches.

## Cache invalidation and freshness

Decision: hybrid freshness policy.

Metadata is used to identify candidate changes; hashes are computed only for content that `mfs` actually reads into cache/index.

Per cached chunk/file, store:

```text
source_size
source_mtime_or_remote_fingerprint
sha256          # only when content was read
indexed_at
remote_seen_at
cache_state     # metadata_only | content_cached | text_indexed | skipped
skip_reason     # too_large | binary | likely_secret | decode_error | unsupported
```

Command behavior:

- `ls`, `tree`, and `find` refresh remote metadata when they can do so cheaply.
- `index`/`update` refresh metadata and reindex only changed, uncached, or unsafe-to-trust entries.
- `grep` and `search --lex` use the local index by default and include freshness/staleness metadata in JSON output.
- `--refresh` forces reread/reindex before answering where applicable.
- Future `--max-age` may reject or warn on stale index entries older than a requested age.
- `changed` compares manifests/index rows using metadata first, hashes when available.

Correctness language:

- Metadata-only results answer "what Modal currently reports."
- Indexed content results answer "what was cached/indexed at `indexed_at`."
- `--refresh` is the path for stronger current-content confidence.

## Safety defaults

- No command downloads a directory recursively unless explicitly requested.
- `get` requires `--recursive` when the remote path is a directory.
- `put` requires `--recursive` when the local path is a directory.
- `cat` has default byte cap.
- `cat --bytes START:LEN` maps to Modal byte-range reads when available; public SDK fallback may read more and slice locally within `--max-bytes`.
- `cat --lines START:END` is text/index-backed or bounded best effort; it must not scan unbounded files silently.
- `index` skips files over default cap unless `--max-bytes` raised.
- `cp` in MVP is only same profile/environment/volume. Cross-volume copy is post-MVP or explicit `get` + `put`.
- `cp --recursive` must fail clearly for v1 Volumes because Modal SDK does not support recursive copy for v1.
- `rm`, overwrite, and future sync-write require `--yes` or `--force` as appropriate.
- JSON errors must be stable enough for agents to branch on.
- Secrets and binary blobs should not be blindly indexed as text.

## Modal-specific constraints to preserve

- Modal Volumes are not a normal live filesystem.
- Remote state can involve commit/reload visibility semantics inside Modal functions.
- CLI operations are explicit remote operations.
- Large file counts and inode limits affect crawl/index strategy.
- Volumes are optimized for write-once/read-many workloads.
- Volumes v1 guidance: best below 50,000 files/directories; hard 500,000 inode limit; avoid more than 5 concurrent commits for small changes.
- Volumes v2 is beta, more scalable, has no total file-count limit, supports at most 262,144 files in a single directory, and limits each file to less than 1 TiB.
- Volumes v2 supports distinct-file concurrent writes from hundreds of containers without expected performance degradation.
- Same-file concurrent writes still have last-write-wins semantics in many circumstances; distributed file locking is not supported.
- Volumes v2 can be committed from shell/Sandbox via `sync /path/to/mountpoint`.

## Mutation/concurrency model

MVP should not pretend to provide locking Modal does not provide.

Resolved MVP stance:

1. Read/query commands are fully parallel-safe.
2. Distinct-path writes are allowed, but output must include operation metadata and warnings when freshness is uncertain.
3. Same-path overwrite/delete/rename is guarded by explicit flags.
4. MVP includes thin write primitives: `get`, `put`, `rm`, and `cp`.
5. MVP does not include a serialized mutation queue; queueing remains a post-MVP option.

Candidate queue design if needed:

```text
mfs mutate enqueue --op put --src ./file --dst modal://profile/env/vol/path
mfs mutate run --queue modal://profile/env/vol/.mfs/mutations
mfs mutate status
```

Queue semantics:

- Serialize writes per target path, or optionally per path prefix.
- Use append-only intent records: operation, target path, source hash, expected prior hash/version if known, created_at, actor.
- Apply with compare-before-write where possible: refuse overwrite when known prior hash changed.
- Write audit records to sidecar index and optionally `.mfs/mutations/log.jsonl` in the Volume.
- Do not claim distributed locking; call it a cooperative mutation queue.

Decision: cooperative queuing is not core to MVP. MVP should warn, expose primitives, and record mutation metadata locally.

## Open decisions for grilling

1. Exact per-profile SDK client plumbing, minimum supported Modal SDK version, and whether private/proto calls are acceptable for byte ranges and `max_entries`.
2. Default max file size for content indexing.
3. MCP server in MVP or after CLI stabilizes.
4. Whether to design for local-only index or index stored inside Modal Volume.
5. Whether `mv` belongs in MVP or waits until after `cp`/`rm` safety semantics are proven.

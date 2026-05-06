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

## Proposed URI

```text
modal://ENV/VOLUME/path/to/file
```

Examples:

```text
modal://main/models/qwen/model.safetensors
modal://dev/agent-workspaces/run-123/trace.jsonl
```

Decision: `ENV` is required in MVP and must not silently default from Modal profile state.

## Alternative remote-filesystem address

Instead of forcing URI syntax into every command, `mfs` can treat Modal Volumes like roots on a remote server:

```text
Volumes/modal/ENV/VOLUME/path/to/file
```

Examples:

```text
Volumes/modal/main/models/qwen/model.safetensors
Volumes/modal/dev/agent-workspaces/run-123/trace.jsonl
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

Resolution: use remote-filesystem paths as the primary CLI UX and keep `modal://ENV/VOLUME/path` as a canonical machine URI accepted everywhere. The environment segment is required in both forms for MVP.

Primary examples:

```text
mfs ls Volumes/modal/main/models/
mfs cat Volumes/modal/main/models/config.json --range 1:120
mfs put ./artifact.bin Volumes/modal/main/artifacts/artifact.bin
```

Machine/canonical examples:

```text
mfs ls modal://main/models/
mfs cat modal://main/models/config.json --range 1:120
```

## MVP commands

```text
mfs ls URI [--json]
mfs tree URI [--depth N] [--limit N] [--json]
mfs stat URI [--json]
mfs cat URI [--range START:END] [--max-bytes N]
mfs get URI LOCAL_DEST [--force]
mfs put LOCAL_PATH URI [--force]
mfs rm URI [--recursive] --yes
mfs cp SRC_URI DST_URI [--recursive] [--force]
mfs find URI --glob GLOB [--size EXPR] [--mtime EXPR] [--json]
mfs grep URI PATTERN [--glob GLOB] [--context N] [--json]
mfs index URI [--store PATH] [--max-bytes N]
mfs update URI [--store PATH]
mfs manifest URI [--jsonl]
mfs changed URI --since MANIFEST_OR_INDEX [--json]
mfs doctor URI [--json]
```

## Later commands

```text
mfs search URI QUERY [--lex|--semantic|--hybrid]
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
    "uri": "modal://main/vol/path",
    "retryable": false
  }
}
```

## Sidecar SQLite model

```sql
create table files (
  volume_uri text not null,
  path text not null,
  type text not null,
  size integer,
  mtime text,
  etag text,
  sha256 text,
  mime text,
  ext text,
  content_cached integer not null default 0,
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

FTS5 virtual table can index `chunks.text` after MVP metadata is stable.

## Safety defaults

- No command downloads a directory recursively unless explicitly requested.
- `cat` has default byte cap.
- `index` skips files over default cap unless `--max-bytes` raised.
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
mfs mutate enqueue --op put --src ./file --dst modal://env/vol/path
mfs mutate run --queue modal://env/vol/.mfs/mutations
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

1. Whether Modal profile/workspace selection is needed in MVP, or environment + active Modal auth is enough.
2. MVP implementation language/package: Python + Click + Modal SDK vs shelling out to `modal volume`.
3. Whether metadata-only index is MVP, or FTS grep/search must be MVP.
4. Cache location and invalidation rules.
5. Default max file size for content indexing.
6. Whether `mfs search` means lexical search first or vector/hybrid search.
7. MCP server in MVP or after CLI stabilizes.
8. Whether to design for local-only index or index stored inside Modal Volume.
9. Whether `mv` belongs in MVP or waits until after `cp`/`rm` safety semantics are proven.
10. Whether to support multiple Modal profiles/workspaces.

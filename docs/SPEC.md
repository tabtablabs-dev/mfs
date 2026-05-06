# mfs Spec

## Goal

Build a Modal Volume query CLI for agents: a filesystem-shaped command surface plus a local SQLite sidecar index that lets agents cheaply inspect, find, grep, manifest, and safely manipulate Modal Volumes while respecting Modal's remote, snapshot/commit/reload semantics.

`mfs` exists because Modal's native CLI is resource-oriented and awkward compared with a typical filesystem workflow. The design target is not POSIX compatibility; it is safe, bounded, machine-readable filesystem querying.

## Command parity stance

Decision: `mfs` targets **remote-agent command parity**, not POSIX parity.

`mfs` should use familiar filesystem verbs when they help transfer shell intuition, but the contract is remote-safe agent operation:

- explicit Modal profile/environment/volume addressing
- bounded defaults for list/read/recursive operations
- JSON output and stable JSON errors for agent branching
- no surprise full-volume crawls or downloads
- no hidden destructive mutation
- honest Modal consistency/concurrency warnings

This means `ls`, `cd`, `cp`, `mv`, `rm`, `mkdir`, and `du` can exist, but they do not imply local mounts, Unix permissions/owners, process-global shell cwd, atomic rename, distributed locks, or unbounded recursive traversal.

`mfs cd` is in scope. It updates persistent `mfs` virtual cwd state under `~/.mfs/`; it does not and cannot change the parent shell process directory.

## Current directory state

Decision: `mfs cd` stores state in `~/.mfs/state.json` using a per-provider/profile/environment map, not a single blind global cwd and not named sessions yet.

Minimal state shape:

```json
{
  "version": 1,
  "default_cwd": "modal://tabtablabs/main/zillow-quadtree-v2",
  "cwd_by_context": {
    "modal/tabtablabs/main": "modal://tabtablabs/main/zillow-quadtree-v2"
  },
  "updated_at": "2026-05-06T00:00:00Z"
}
```

Rules:

- `mfs cd TARGET` resolves `TARGET` to a canonical remote URI, verifies it is a directory-like target, then updates `default_cwd` and the matching `cwd_by_context` entry.
- `mfs cd` with no target resets `default_cwd` to the virtual root `Volumes/`.
- `mfs cd ..` resolves against the active `default_cwd`.
- Commands that omit `TARGET` use `default_cwd`.
- `mfs ls` with no target uses `default_cwd`; if no cwd is set, it returns `CWD_NOT_SET` instead of falling back to root discovery.
- Commands that receive relative remote paths resolve them against `default_cwd`.
- Context keys are stable strings like `modal/PROFILE/ENV`.
- `mfs pwd` is first-class and reports the active `default_cwd`, the resolved context key, and the state file path.
- Named sessions and per-project cwd state are post-MVP unless a real workflow proves they are needed.

```text
mfs pwd [--json]
```

After `mfs cd`, a subsequent `mfs ls` lists root discovery entries from `Volumes/`. This is not recursive traversal of every directory in every Volume; broad tree walks remain bounded through `tree`, `du`, index/update, or explicit recursive budgets.

Example JSON:

```json
{
  "cwd": "modal://tabtablabs/main/zillow-quadtree-v2",
  "context": "modal/tabtablabs/main",
  "state_path": "~/.mfs/state.json"
}
```

## Relative path resolution

Decision: command targets resolve shell-like against the current virtual cwd.

Given:

```text
cwd = modal://tabtablabs/main/zillow-quadtree-v2/a/b
```

Resolution examples:

```text
mfs ls cache     -> modal://tabtablabs/main/zillow-quadtree-v2/a/b/cache
mfs cd ..        -> modal://tabtablabs/main/zillow-quadtree-v2/a
mfs cd /cache    -> modal://tabtablabs/main/zillow-quadtree-v2/cache
mfs cd /         -> modal://tabtablabs/main/zillow-quadtree-v2
mfs cd Volumes/  -> Volumes/
mfs cd           -> Volumes/
```

Rules:

- `foo/bar` resolves relative to `default_cwd`.
- `..` and `.` are normalized within the virtual path.
- Leading `/foo` means from the current Modal Volume root, not local filesystem root and not the `Volumes/` virtual root.
- `Volumes/` is the explicit virtual root syntax.
- `modal://PROFILE/ENV/VOLUME/path` and `Volumes/modal/PROFILE/ENV/VOLUME/path` remain absolute remote targets.
- Leading `/foo` requires the current cwd to be inside a specific Modal Volume. If cwd is `Volumes/`, `Volumes/modal`, `Volumes/modal/PROFILE`, or `Volumes/modal/PROFILE/ENV`, return `CWD_VOLUME_REQUIRED` instead of guessing a volume.

## `ls` hidden-file behavior

Decision: `mfs ls` follows shell-like dotfile behavior.

- By default, `mfs ls` hides entries whose basename starts with `.`.
- `mfs ls -a` and `mfs ls --all` include dotfiles.
- Filtering applies after Modal returns entries and before output/truncation metadata is finalized.
- JSON output includes `include_hidden` so agents can branch deterministically.

Example JSON field:

```json
{
  "include_hidden": false
}
```

## `ls -l` long-format behavior

Decision: `mfs ls -l` is an honest Modal metadata long format, not a fake POSIX long listing.

Modal listing metadata supports practical remote fields such as:

```text
type  size  mtime  path/name
```

`mfs ls -l` must not invent Unix owner, group, permission, hard-link count, inode, or device fields. If future adapters expose provider-specific metadata, JSON may include it under explicit provider metadata keys rather than rendering it as POSIX truth.

Human example:

```text
file       83  2026-02-12T10:55:07Z  campaign.json
directory   0  2026-02-11T17:20:38Z  cache
```

JSON should include the same entry fields already used by normal `ls`, plus `long_format: true` at the response level.

## `du` budget behavior

Decision: `mfs du` is read-only and may use conservative default traversal budgets, but it must be honest when the result is partial.

`du` command shape:

```text
mfs du TARGET [-s] [-h] [--depth N] [--limit N] [--json]
```

Semantics:

- `du -s TARGET` summarizes the target within the active traversal budget.
- `du -sh TARGET` adds human-readable size formatting.
- Default live traversal budget is depth 8 and 10,000 entries.
- `--depth N` and `--limit N` override the defaults.
- `du` is never an unbounded full-volume crawl by default.
- When traversal hits depth, entry, API, or path-breadth limits, JSON must report `partial: true` and include the limiting factor.
- Human output should visibly mark partial summaries instead of looking authoritative.
- If a sidecar index exists and is selected later, `du` may answer from index rows, but JSON must identify whether the answer is `live`, `indexed`, or mixed.

Example JSON shape:

```json
{
  "uri": "modal://tabtablabs/main/vol/path",
  "size_bytes": 123456,
  "human_size": "121 KiB",
  "partial": true,
  "entry_count": 10000,
  "limit": 10000,
  "depth": 8,
  "limited_by": "entry_limit",
  "source": "live"
}
```

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

Resolved adapter detail from spike `spikes/001-modal-profile-adapter`: `mfs` should not use `Client.from_env()` in adapter core. `Client.from_env()` is a process singleton and is a poor fit for paths that carry their own `PROFILE` segment. The adapter should resolve explicit profile credentials with `modal.config.config.get(profile=..., use_env=False)` and open/cache a private Modal `_Client` per `(profile, server_url)`.

Public SDK remains preferred where it preserves bounded semantics, but adapter-confined private/proto calls are required for MVP agent safety in Modal SDK `1.3.5`:

- Use the internal async `_VolumeManager.list(..., client=...)` for profile-scoped Volume discovery; passing a direct private client into the public synchronicity wrapper hung in the live spike.
- Use `VolumeGetFile2Request(start,len)` for byte ranges; public `Volume.read_file()` does not expose range parameters.
- Use `VolumeListFilesRequest/VolumeListFiles2Request(max_entries)` for bounded listings; public `Volume.listdir()`/`iterdir()` do not expose `max_entries`.
- For file listings, try v2 RPC first and fall back to v1 on unsupported-version errors. Do not trust `VolumeList` metadata alone for v1/v2 selection; the live spike saw `v1` metadata for volumes that required the v2 listing RPC.

`mfs doctor` must report Modal SDK version, active adapter path, profile source, and private/proto availability. If private internals are unavailable or incompatible, commands that depend on bounded semantics must fail closed rather than fall back to unbounded reads/listings.

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

## v0.0.1 release slice

v0.0.1 is an OSS alpha and intentionally smaller than the full MVP command list. It ships the bounded read-only core needed to validate the architecture:

```text
mfs version [--json]
mfs doctor [TARGET] [--json]
mfs ls TARGET [--limit N] [--recursive] [--json]
mfs stat TARGET [--json]
mfs cat TARGET [--bytes START:LEN] [--max-bytes N] [--json]
```

Deferred from v0.0.1: sidecar index, lexical search, manifests/change detection, and write primitives. These remain in the MVP spec below but must not be described as shipped until implemented and tested.

## MVP commands

```text
mfs ls [URI] [-a] [-l] [--limit N] [--recursive] [--json]
mfs cd [URI|..] [--json]  # no target resets to Volumes/
mfs pwd [--json]
mfs tree URI [--depth N] [--limit N] [--json]
mfs stat URI [--json]
mfs cat URI [--bytes START:LEN] [--lines START:END] [--max-bytes N] [--refresh]
mfs get URI LOCAL_DEST [--recursive] [--force]
mfs put LOCAL_PATH URI [--recursive] [--force]
mfs rm URI [--recursive] --yes
mfs cp SRC_URI DST_URI [--recursive] [--force]  # MVP: same profile/env/volume only
mfs mv SRC_URI DST_URI [--force] [--yes]
mfs mkdir URI [--parents] [--json]
mfs du URI [-s] [-h] [--depth N] [--limit N] [--json]
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

Current-directory errors use a stable `CWD_NOT_SET` code. Example:

```json
{
  "error": {
    "code": "CWD_NOT_SET",
    "message": "No mfs current directory is set; run mfs cd TARGET or pass TARGET explicitly",
    "retryable": false
  }
}
```

Leading-slash in-volume paths require cwd inside a concrete Modal Volume. If cwd is only a discovery/root context, return `CWD_VOLUME_REQUIRED`:

```json
{
  "error": {
    "code": "CWD_VOLUME_REQUIRED",
    "message": "Absolute-in-volume path '/cache' requires cwd inside a Modal Volume; use Volumes/... or cd into a volume first",
    "retryable": false
  }
}
```

Modal broad-path failures are first-class errors, not implementation bugs. When Modal returns `ConflictError: Too many files to list in the path`, `mfs` must return a stable `PATH_TOO_BROAD` JSON error with the queried URI, requested limit/depth where relevant, and a suggestion to narrow the prefix. It must not silently switch to unbounded recursive listing or downloading.

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

Mutation guardrail decision: mutation commands are real commands, not plan-only by default, but destructive and overwrite behavior requires explicit non-interactive confirmation flags.

Baseline guardrails:

- `rm TARGET` fails unless `--yes` is passed.
- `rm -r TARGET` / `rm --recursive TARGET` fails unless both recursion and `--yes` are explicit.
- `cp SRC DST` may create a missing destination, but must not overwrite an existing remote path unless `--force` is passed.
- `mv SRC DST` may rename/move into a missing destination, but must not overwrite an existing remote path unless `--force` is passed; same-path or same-prefix collisions must fail clearly.
- `put LOCAL DST` must not overwrite an existing remote path unless `--force` is passed.
- `mkdir TARGET` creates a new Modal Volume v2 when `TARGET` resolves to `Volumes/modal/PROFILE/ENV/VOLUME`.
- `mkdir TARGET` creates a directory-like path target using a hidden `.mfskeep` marker file when `TARGET` resolves inside an existing Volume; parent creation requires `--parents`.
- `-i` / `--interactive` may exist for human CLI parity, but it is not the agent contract. Agents should use explicit `--yes`, `--force`, `--dry-run`, and JSON output instead of prompt-dependent flows.
- Destructive and overwrite JSON responses include operation metadata: `operation`, `source_uri` when applicable, `target_uri`, `recursive`, `overwrote`, and `confirmed_by_flag`.

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
- `mfs` creates new Modal Volumes as Volumes v2 only.

## Mutation/concurrency model

MVP should not pretend to provide locking Modal does not provide.

Resolved MVP stance:

1. Read/query commands are fully parallel-safe.
2. Distinct-path writes are allowed, but output must include operation metadata and warnings when freshness is uncertain.
3. Same-path overwrite/delete/rename is guarded by explicit flags.
4. MVP includes thin write primitives: `get`, `put`, `rm`, `cp`, `mv`, and `mkdir` once their guardrails are implemented and tested.
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

## Implementation order

Decision: implement navigation/read parity before mutations.

Order:

1. `cd`, `pwd`, omitted-target cwd resolution, `ls -a`, and `ls -l`.
2. Read-only `du` after recursive budget semantics are settled.
3. `tree` and metadata/index/search flows.
4. Guarded mutation commands: `get`, `put`, `rm`, `cp`, `mv`, and `mkdir`.

Rationale: cwd/path resolution is shared infrastructure for almost every later command. It should be stable, tested, and JSON-observable before remote mutation commands depend on it.

## Open decisions for grilling

1. Default max file size for future content indexing.
2. MCP server in MVP or after CLI stabilizes.
3. Whether to design for local-only index or index stored inside Modal Volume.
4. Whether `mv` belongs in MVP or waits until after `cp`/`rm` safety semantics are proven.

# Context

## Domain glossary

### Modal Volume

Durable remote filesystem-like storage managed by Modal. `mfs` treats it as the remote source of truth for bytes and directory state.

### Volume URI

Canonical machine address for a Modal Volume path.

```text
modal://PROFILE/ENV/VOLUME/path
```

Decision: `mfs` exposes remote-filesystem path syntax (`Volumes/modal/PROFILE/ENV/VOLUME/path`) as the primary user-facing address, while accepting explicit URI syntax (`modal://PROFILE/ENV/VOLUME/path`) as canonical machine syntax.

### Remote Filesystem Path

Filesystem-like address that treats Modal Volumes as mounted remote roots without actually mounting them.

```text
Volumes/modal/PROFILE/ENV/VOLUME/path
```

The profile and environment segments are required in MVP to avoid hidden Modal default auth/profile/environment state.

### Sidecar Index

Local SQLite database maintained by `mfs`. Stores file metadata, optional content chunks, FTS rows, and freshness data. It is a query accelerator, not the source of truth.

### Manifest

Portable JSONL snapshot of known remote file metadata: path, type, size, mtime/fingerprint when available, hashes when computed, MIME/type guesses, and indexing timestamps.

### Content Cache

Local bounded cache of downloaded file bytes or text chunks used for `cat`, `grep`, and search. Cache can be stale and must expose freshness metadata.

Default location is user cache (`~/.cache/mfs/`), but commands accept `--store` for repo-local/project-pinned indexes such as `.mfs/index.sqlite`.

Freshness policy is hybrid: metadata detects candidate changes; sha256 is computed only for cached/indexed content; `--refresh` forces reread/reindex.

### Agent Query

A bounded, machine-readable operation an agent can run safely to answer filesystem questions: list, tree, stat, find, grep, search, manifest, changed, diff, cat range.

### Destructive Operation

Any command that removes or overwrites remote data: `rm`, `put --force`, `mv`, `cp --force`, future sync write modes. Requires explicit confirmation.

## Resolved decisions

- Canonical product frame: `mfs` is a **Modal Volume query CLI for agents**. It exists because Modal's native CLI is awkward for normal filesystem-style workflows and not shaped for repeated bounded agent queries.
- `mfs` is Modal-specific first; backend abstraction can wait.
- Sidecar index is required for useful agent coverage.
- POSIX mount is not MVP.
- JSON output is first-class.
- Volumes are treated as write-once/read-many optimized storage; mutation flows must make concurrency semantics explicit.
- MVP includes thin write primitives (`put`, `get`, `rm`, `cp`) with guardrails; it does not include a mutation queue.
- Remote filesystem paths require explicit profile and environment segments: `Volumes/modal/PROFILE/ENV/VOLUME/path`.
- Modal adapter is SDK-first, not a wrapper around the `modal volume` CLI.
- MVP index includes metadata, bounded text content cache, and SQLite FTS5 lexical search; semantic/vector search is post-MVP.
- Store/cache policy is hybrid: default to user cache, allow explicit `--store` for repo-local reproducibility.
- Cache invalidation policy is hybrid: metadata for change candidates, hashes for cached content, refresh flags for forcing correctness.

## Modal Volume concurrency facts

- Modal supports concurrent modification from multiple containers, but concurrent modification of the same file should be avoided.
- Same-file concurrent writes are last-write-wins; data absent from the final committer can be lost.
- Distributed file locking is not supported.
- Volumes v1 guidance: avoid more than 5 concurrent commits for small changes; commits can contend.
- Volumes v2 improves distinct-file concurrent writing: hundreds of containers can write to distinct files without expected performance degradation.
- Volumes v2 still has unacceptable same-file last-write-wins semantics for most applications, so a particular file should only have one writer at a time.
- Volumes v2 can commit via `sync /path/to/mountpoint` inside a Sandbox or Modal shell.

## Open language questions


# Context

## Domain glossary

### Modal Volume

Durable remote filesystem-like storage managed by Modal. `mfs` treats it as the remote source of truth for bytes and directory state.

### Volume URI

Canonical address for a Modal Volume path.

```text
modal://ENV/VOLUME/path
```

Open question: whether `ENV` should be required, optional, or encoded through a profile/default.

### Sidecar Index

Local SQLite database maintained by `mfs`. Stores file metadata, optional content chunks, FTS rows, and freshness data. It is a query accelerator, not the source of truth.

### Manifest

Portable JSONL snapshot of known remote file metadata: path, type, size, mtime/fingerprint when available, hashes when computed, MIME/type guesses, and indexing timestamps.

### Content Cache

Local bounded cache of downloaded file bytes or text chunks used for `cat`, `grep`, and search. Cache can be stale and must expose freshness metadata.

### Agent Query

A bounded, machine-readable operation an agent can run safely to answer filesystem questions: list, tree, stat, find, grep, search, manifest, changed, diff, cat range.

### Destructive Operation

Any command that removes or overwrites remote data: `rm`, `put --force`, `mv`, `cp --force`, future sync write modes. Requires explicit confirmation.

## Resolved decisions

- `mfs` is Modal-specific first; backend abstraction can wait.
- Sidecar index is required for useful agent coverage.
- POSIX mount is not MVP.
- JSON output is first-class.

## Open language questions

- Is this a "filesystem query CLI", "remote volume indexer", or "agent filesystem adapter"?
- Should remote identity be `modal://ENV/VOLUME/path`, `modal://PROFILE/ENV/VOLUME/path`, or flags plus path?
- Is `search` lexical-only for MVP, or does MVP include semantic/vector search?

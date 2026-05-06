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

Root discovery paths are also part of the filesystem metaphor:

```text
Volumes/
Volumes/modal/
Volumes/modal/PROFILE/
Volumes/modal/PROFILE/ENV/
```

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

### Remote-Agent Command Parity

`mfs` uses familiar filesystem verbs where they help users and agents transfer shell intuition: `ls`, `cd`, `cp`, `mv`, `rm`, `mkdir`, `du`, and related query commands. Parity means command-shaped familiarity, not POSIX compatibility. Every operation remains explicit, bounded, JSON-friendly where relevant, and honest about Modal's remote consistency model.

Remote-agent command parity does not imply local mounts, Unix owner/group/permission fidelity, process-global current directory, atomic rename semantics, distributed locks, or unbounded recursive traversal.

### mfs Current Directory

Persistent virtual working directory used by `mfs cd` and commands that accept relative remote paths. It is `mfs` application state, stored under `~/.mfs/`, not the shell process current directory.

Current-directory state uses a per-profile/environment map in `~/.mfs/state.json`. It keeps a `default_cwd` plus `cwd_by_context` keys such as `modal/tabtablabs/main`, so switching between Modal profiles/environments does not silently reuse the wrong remote location.

`mfs pwd` is the first-class way to inspect this state. Users and agents should not need to read `~/.mfs/state.json` directly for normal workflows.

`mfs cd` with no target resets the current directory to the virtual root `Volumes/`. A subsequent `mfs ls` performs root discovery from there. This is not recursive traversal of every directory in every Volume.

Relative paths resolve shell-like against the current virtual cwd. If cwd is `modal://PROFILE/ENV/VOLUME/a/b`, then `cache` resolves to `modal://PROFILE/ENV/VOLUME/a/b/cache`, `..` resolves to `modal://PROFILE/ENV/VOLUME/a`, and `/cache` resolves to `modal://PROFILE/ENV/VOLUME/cache`. `Volumes/` remains the explicit virtual root.

### Destructive Operation

Any command that removes or overwrites remote data: `rm`, `put --force`, `mv`, `cp --force`, future sync write modes. Requires explicit non-interactive confirmation such as `--yes` or `--force`; interactive `-i` can exist for humans, but agents must not depend on prompts.

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
- Modal file listings expose `path`, `type`, `mtime`, and `size`; no remote etag/content hash should be assumed.
- MVP `cp` is same-volume only; cross-volume copy is post-MVP.
- `mfs` will target remote-agent command parity rather than POSIX parity.
- `mfs cd` is in scope; its current-directory state lives under `~/.mfs/` rather than in shell cwd.
- `mfs cd` state model is `~/.mfs/state.json` with `default_cwd` and `cwd_by_context` keyed by provider/profile/environment; named sessions can wait.
- `mfs pwd` is first-class and reports the current virtual cwd plus state metadata, including JSON output for agents.
- `mfs ls` with no target means list the current virtual cwd. If no cwd exists, return `CWD_NOT_SET`; do not silently list `Volumes/`.
- `mfs cd` with no target resets cwd to virtual root `Volumes/`; then `mfs ls` performs bounded root discovery, not recursive all-volume listing.
- `mfs ls` hides dotfiles by default. `mfs ls -a` / `mfs ls --all` includes entries whose basename starts with `.`. JSON output includes `include_hidden`.
- `mfs ls -l` is an honest Modal metadata long format: type, size, mtime, and path/name. It must not fake Unix owner, group, or permission fields.
- Mutation commands use agent-safe defaults: destructive actions and overwrites require explicit non-interactive flags (`--yes`/`--force` as appropriate). POSIX-style `-i` prompts are human sugar, not the agent contract.
- Implementation order is navigation/read parity first (`cd`, `pwd`, `ls -a`, `ls -l`), then read-only `du`, then mutation commands. Do not jump to `cp`/`mv`/`rm` before cwd/path resolution is stable and tested.
- `mfs du` is read-only but recursive enough to need budgets. `du -s` / `du -sh` default to depth 8 and 10,000 entries, with explicit `--depth` / `--limit` overrides, and must report `partial=true` when caps are hit.
- Relative command targets resolve shell-like against cwd. `foo` is cwd-relative, `..` is parent, `/foo` is rooted at the current Modal Volume, and `Volumes/` is the explicit virtual root.
- If a command uses a leading-slash in-volume target such as `/foo` while cwd is not inside a specific Modal Volume, return `CWD_VOLUME_REQUIRED` rather than guessing a volume or treating `/` as local root.
- v0.0.1 release slice is read-only: `version`, `doctor`, root discovery, bounded `ls`, `stat`, and bounded `cat`.
- v0.0.1 Modal adapter resolves explicit profile credentials with `use_env=False`, avoids `Client.from_env()`, uses a private `_Client`, tries v2 file-list RPC before v1 fallback, and fails closed when bounded private/proto calls are unavailable.
- Broad Modal paths can fail even with `max_entries`; surface this as `PATH_TOO_BROAD` and ask the agent/user to narrow the prefix.

## Modal Volume concurrency facts

- Modal supports concurrent modification from multiple containers, but concurrent modification of the same file should be avoided.
- Same-file concurrent writes are last-write-wins; data absent from the final committer can be lost.
- Distributed file locking is not supported.
- Volumes v1 guidance: avoid more than 5 concurrent commits for small changes; commits can contend.
- Volumes v2 improves distinct-file concurrent writing: hundreds of containers can write to distinct files without expected performance degradation.
- Volumes v2 still has unacceptable same-file last-write-wins semantics for most applications, so a particular file should only have one writer at a time.
- Volumes v2 can commit via `sync /path/to/mountpoint` inside a Sandbox or Modal shell.
- `mfs mkdir NAME` at an environment root creates a new Modal Volume, and new Modal Volumes must always be Volumes v2.

## Open language questions

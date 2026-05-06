# Plans

## Completed: v0.0.1 OSS alpha

Objective: ship a small, honest release candidate based on the spec without overbuilding.

Released slice:

- URI/virtual path parser.
- Stable JSON and JSON errors.
- `version`.
- `doctor`.
- Root discovery.
- Bounded read-only `ls`.
- `stat`.
- Bounded byte-range `cat`.
- Modal profile adapter that avoids `Client.from_env()` and fails closed on unsafe unbounded fallbacks.

## Next: v0.0.2 / v0.1.0 candidates

Decision: implement navigation/read parity before mutations. Cwd/path resolution becomes a shared dependency for `ls`, `du`, `cp`, `mv`, `rm`, `mkdir`, `find`, and later MCP tools, so make it boring first.

1. Navigation/read parity slice:
   - `cd` with persistent `~/.mfs/state.json` state
   - `pwd`
   - omitted-target resolution from cwd
   - `ls -a` / `--all`
   - `ls -l` honest Modal metadata long format
2. Add read-only `du` with default budget depth 8 / limit 10,000 entries, `partial` metadata, and explicit `--depth` / `--limit` overrides.
3. Add `tree` as bounded repeated `ls` with depth/entry budgets.
4. Add sidecar SQLite metadata schema and `index/update` for metadata only.
5. Add bounded text cache and FTS5-backed `grep` / `search --lex`.
6. Add `manifest` and `changed` from index rows.
7. Add guarded mutation primitives only after cwd/path/read behavior is stable:
   - `get`
   - `put`
   - `rm`
   - same-volume `cp`
   - `mv`
   - `mkdir`

## Release discipline

- Do not call planned commands shipped until they exist in `src/mfs/cli.py` and have tests.
- Keep all remote operations bounded by default.
- Prefer stable JSON errors over clever fallback behavior.

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

1. Add `tree` as bounded repeated `ls` with depth/entry budgets.
2. Add sidecar SQLite metadata schema and `index/update` for metadata only.
3. Add bounded text cache and FTS5-backed `grep` / `search --lex`.
4. Add `manifest` and `changed` from index rows.
5. Add guarded write primitives only after read/index behavior is stable:
   - `get`
   - `put`
   - `rm`
   - same-volume `cp`

## Release discipline

- Do not call planned commands shipped until they exist in `src/mfs/cli.py` and have tests.
- Keep all remote operations bounded by default.
- Prefer stable JSON errors over clever fallback behavior.

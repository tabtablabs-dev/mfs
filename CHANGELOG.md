# Changelog

All notable changes to `mfs` will be documented here.

## v0.0.1 - 2026-05-06

Initial OSS alpha release.

### Added

- Python package and `mfs` console script.
- Explicit target parser for:
  - `Volumes/modal/PROFILE/ENV/VOLUME/path`
  - `modal://PROFILE/ENV/VOLUME/path`
- Root discovery:
  - `Volumes/`
  - `Volumes/modal`
  - `Volumes/modal/PROFILE`
  - `Volumes/modal/PROFILE/ENV`
- Read-only live Modal commands:
  - `mfs doctor`
  - `mfs ls`
  - `mfs stat`
  - `mfs cat`
- Stable JSON output and JSON errors.
- Explicit profile credential lookup without `Client.from_env()`.
- Bounded Modal listing through adapter-confined private/proto RPCs.
- Bounded byte reads through `VolumeGetFile2(start,len)`.
- Unit tests for version, parsing, root JSON, error JSON, and byte-range guards.
- OSS release docs and MIT license.

### Safety

- v0.0.1 is read-only against Modal Volumes.
- Listings default to non-recursive and capped by `--limit`.
- `cat` is capped by `--max-bytes`.
- Broad Modal path failures are surfaced as `PATH_TOO_BROAD`.

### Deferred

- Sidecar SQLite index and FTS search.
- `find`, `grep`, `search`, `manifest`, and `changed`.
- Guarded write commands: `get`, `put`, `rm`, `cp`.
- MCP server.

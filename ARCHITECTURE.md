# Architecture

## Implemented v0.0.1 layers

```text
Click CLI
  -> output/error helpers
    -> target parser
    -> Modal adapter
```

v0.0.1 is intentionally read-only and does not yet include the sidecar index or content cache layers.

## Boundaries

- CLI layer parses args and formats human/JSON output only.
- Target parser owns `Volumes/modal/PROFILE/ENV/VOLUME/path` and `modal://PROFILE/ENV/VOLUME/path` grammar.
- Output layer owns stable JSON and JSON error serialization.
- Modal adapter owns Modal SDK calls, explicit per-profile credential resolution, private `_Client` lifecycle, and version-gated private/proto fallbacks for bounded byte-range reads and `max_entries` listing.
- Future sidecar index adapter owns SQLite schema/migrations/query planning, including FTS5 lexical search.
- Future content cache adapter owns bounded downloaded bytes/text, chunking, safety skips, eviction, freshness metadata, and selected store/cache path resolution.

## Dependency direction

Adapters depend inward on domain types where needed; domain parsing and output do not depend on Click or subprocess details.

## Package layout

```text
src/mfs/
  __init__.py        version marker
  cli.py             Click command surface
  errors.py          stable machine-readable errors
  modal_adapter.py   Modal SDK/private-proto adapter
  output.py          JSON/human output helpers
  paths.py           target parsing and canonicalization
```

Planned later:

```text
src/mfs/
  index.py           SQLite metadata + FTS5
  cache.py           bounded content cache
  manifest.py        JSONL manifest generation/comparison
  commands/          larger command handlers when CLI grows
```

## Modal adapter stance

`mfs` is SDK-first, but Modal SDK `1.3.5+` does not expose all bounded operations through public methods. v0.0.1 therefore uses adapter-confined private/proto calls:

- explicit profile credentials through `modal.config.config.get(profile=..., use_env=False)`
- private `_Client` instead of `Client.from_env()`
- internal `_VolumeManager` for profile-scoped volume discovery
- `VolumeListFiles2/VolumeListFiles(max_entries=...)` for bounded listings
- `VolumeGetFile2(start,len)` for bounded `cat`

If those private/proto capabilities are unavailable, commands that depend on bounded semantics must fail closed instead of falling back to unbounded reads/listings.

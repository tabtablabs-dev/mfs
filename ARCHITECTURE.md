# Architecture

## Implemented layers

```text
Click CLI
  -> output/error helpers
    -> target parser
    -> persistent cwd state
    -> Modal adapter
    -> SQLite sidecar index
```

The package version remains `v0.0.1`, but the current worktree implements the MVP command surface from `docs/SPEC.md`.

## Boundaries

- CLI layer parses args and formats human/JSON output only.
- Target parser owns `Volumes/modal/PROFILE/ENV/VOLUME/path` and `modal://PROFILE/ENV/VOLUME/path` grammar.
- State layer owns `~/.mfs/state.json`, cwd resolution, context keys, and `cd`/`pwd` payloads.
- Output layer owns stable JSON and JSON error serialization.
- Modal adapter owns Modal SDK calls, explicit per-profile credential resolution, private `_Client` lifecycle, and version-gated private/proto fallbacks for bounded byte-range reads and `max_entries` listing.
- Sidecar index adapter owns SQLite schema/query planning, FTS5 lexical search, metadata rows, text chunks, and selected store path resolution.
- Content caching is represented by bounded text chunks in the sidecar store; binary/secret/too-large files are skipped rather than blindly indexed as text.

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
  state.py           persistent virtual cwd state
  index.py           SQLite metadata + FTS5 sidecar store
```

## Modal adapter stance

`mfs` is SDK-first, but Modal SDK `1.3.5+` does not expose all bounded operations through public methods. v0.0.1 therefore uses adapter-confined private/proto calls:

- explicit profile credentials through `modal.config.config.get(profile=..., use_env=False)`
- private `_Client` instead of `Client.from_env()`
- internal `_VolumeManager` for profile-scoped volume discovery
- `VolumeListFiles2/VolumeListFiles(max_entries=...)` for bounded listings
- `VolumeGetFile2(start,len)` for bounded `cat`

If those private/proto capabilities are unavailable, commands that depend on bounded semantics must fail closed instead of falling back to unbounded reads/listings.

## Mutation stance

Guarded write commands are exposed through the Modal adapter:

- `put` uses `Volume.batch_upload()`.
- `get` reads explicit files and explicit recursive directory entries.
- `rm` uses `Volume.remove_file()` after `--yes`.
- `cp` uses `Volume.copy_files()` only within the same profile/environment/volume.
- `mv` is copy-then-remove and requires `--yes`.
- `mkdir` at an environment root creates a new Modal Volume v2.
- `mkdir` inside a Volume creates directory-like prefixes by uploading a hidden `.mfskeep` marker file because Modal's SDK does not expose an explicit mkdir primitive.

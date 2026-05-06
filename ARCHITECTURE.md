# Architecture

## Proposed layers

```text
CLI commands
  -> command handlers / output formatting
    -> domain services
      -> Modal adapter
      -> sidecar index adapter
      -> content cache adapter
```

## Boundaries

- CLI layer parses args and formats human/JSON output only.
- Domain services own safety policy, URI parsing, caps, and freshness semantics.
- Modal adapter owns Modal Python SDK calls, per-profile client resolution, and any version-gated private/proto fallbacks for bounded byte-range reads or `max_entries` listing.
- Sidecar index adapter owns SQLite schema/migrations/query planning, including FTS5 lexical search.
- Content cache adapter owns bounded downloaded bytes/text, chunking, safety skips, eviction, freshness metadata, and selected store/cache path resolution.

## Dependency direction

Adapters depend inward on domain types where needed; domain does not depend on Click or subprocess details.

## Likely Python package layout

```text
src/mfs/
  __init__.py
  cli.py
  uri.py
  config.py
  modal_adapter.py
  index.py
  cache.py
  commands/
  output.py
  errors.py
```

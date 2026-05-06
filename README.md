# mfs

Modal Volume filesystem/query CLI for agents.

`mfs` wraps Modal Volumes with a filesystem-shaped, agent-safe command surface plus a local SQLite index for cheap discovery, grep, search, manifests, and change detection.

## Status

Spec-first repo. No implementation yet.

## Problem

Modal Volumes are generous and useful as durable remote storage, but their CLI is resource-oriented rather than agent-query-oriented. Agents need to ask filesystem questions repeatedly without recursively downloading or listing everything every turn.

## Intended shape

```text
mfs ls modal://ENV/VOLUME/path --json
mfs tree modal://ENV/VOLUME/path --depth 3 --limit 500
mfs stat modal://ENV/VOLUME/path --json
mfs cat modal://ENV/VOLUME/path --range 1:200
mfs find modal://ENV/VOLUME --glob '**/*.py'
mfs grep modal://ENV/VOLUME 'pattern' --glob '**/*.{md,py,txt}'
mfs index modal://ENV/VOLUME --store .mfs/index.sqlite
mfs search modal://ENV/VOLUME 'natural language query'
```

See `docs/SPEC.md` and `CONTEXT.md`.

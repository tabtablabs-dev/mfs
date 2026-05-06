# mfs

Modal Volume filesystem/query CLI for agents.

`mfs` wraps Modal Volumes with a filesystem-shaped, agent-safe command surface plus a local SQLite index for cheap discovery, grep, search, manifests, and change detection.

## Status

Spec-first repo. No implementation yet.

## Problem

Modal Volumes are generous and useful as durable remote storage, but their CLI is resource-oriented rather than agent-query-oriented. Agents need to ask filesystem questions repeatedly without recursively downloading or listing everything every turn.

## Intended shape

```text
mfs ls Volumes/modal/PROFILE/ENV/VOLUME/path --json
mfs tree Volumes/modal/PROFILE/ENV/VOLUME/path --depth 3 --limit 500
mfs stat Volumes/modal/PROFILE/ENV/VOLUME/path --json
mfs cat Volumes/modal/PROFILE/ENV/VOLUME/path --range 1:200
mfs find Volumes/modal/PROFILE/ENV/VOLUME --glob '**/*.py'
mfs grep Volumes/modal/PROFILE/ENV/VOLUME 'pattern' --glob '**/*.{md,py,txt}'
mfs index Volumes/modal/PROFILE/ENV/VOLUME --store .mfs/index.sqlite
mfs search Volumes/modal/PROFILE/ENV/VOLUME 'natural language query'
```

See `docs/SPEC.md` and `CONTEXT.md`.

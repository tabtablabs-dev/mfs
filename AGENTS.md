# AGENTS.md

## Purpose

`mfs` is a Modal Volume filesystem/query CLI for agents. It exposes remote Modal Volumes through stable, JSON-friendly commands and maintains a local SQLite sidecar index for search, manifests, and change detection.

## Current status

v0.0.1 alpha implementation exists. The release slice is read-only and intentionally smaller than the full spec: `version`, `doctor`, root discovery, bounded `ls`, `stat`, and bounded `cat`. Do not claim sidecar index, search, manifests, or write primitives are implemented until they are shipped and tested.

## Command surface

Implemented v0.0.1 commands:

```bash
uv run mfs version --json
uv run mfs doctor Volumes/modal/PROFILE/ENV --json
uv run mfs ls Volumes/modal/PROFILE/ENV --limit 20 --json
uv run mfs stat Volumes/modal/PROFILE/ENV/VOLUME/path --json
uv run mfs cat Volumes/modal/PROFILE/ENV/VOLUME/path --bytes 0:4096 --json
```

Project checks:

```bash
just check
uv build
```

## File map

```text
README.md          project overview and v0.0.1 usage
CHANGELOG.md       release history
CONTEXT.md         domain glossary and resolved language
docs/SPEC.md       product/technical spec under active grilling
docs/releases/     release notes
src/mfs/           implementation
tests/             pytest coverage
ARCHITECTURE.md    boundaries and package layout
```

## Constraints

- Prefer Python + Click for CLI unless spec changes.
- Prefer `uv_build` packaging.
- All agent-facing commands need `--json` or JSON output mode.
- Remote reads must be bounded by defaults: no surprise full-volume downloads.
- Destructive commands require explicit confirmation flags.
- Modal commit/reload consistency must be visible, not hidden.

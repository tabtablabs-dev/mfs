# AGENTS.md

## Purpose

`mfs` is a Modal Volume filesystem/query CLI for agents. It exposes remote Modal Volumes through stable, JSON-friendly commands and maintains a local SQLite sidecar index for search, manifests, and change detection.

## Current status

Spec-first repo. Do not implement large surfaces before `docs/SPEC.md` decisions are resolved.

## Command surface

Planned local commands:

```bash
just check
just format
just test
just lint
```

Until implementation exists, docs validation is manual:

```bash
git status --short
```

## File map

```text
README.md          project overview
CONTEXT.md         domain glossary and resolved language
docs/SPEC.md       product/technical spec under active grilling
docs/PLANS.md      active execution plan
ARCHITECTURE.md    proposed boundaries
```

## Constraints

- Prefer Python + Click for CLI unless spec changes.
- Prefer `uv_build` packaging.
- All agent-facing commands need `--json` or JSON output mode.
- Remote reads must be bounded by defaults: no surprise full-volume downloads.
- Destructive commands require explicit confirmation flags.
- Modal commit/reload consistency must be visible, not hidden.

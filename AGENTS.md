# AGENTS.md

## Purpose

`mfs` is a Modal Volume filesystem/query CLI for agents. It exposes remote Modal Volumes through stable, JSON-friendly commands and maintains a local SQLite sidecar index for search, manifests, and change detection.

## Current status

The package version is still `v0.0.1`, but the current worktree implements the MVP command surface from `docs/SPEC.md` beyond the original read-only alpha slice. It includes cwd navigation, bounded read/traversal commands, SQLite sidecar indexing/search, manifests/change detection, and guarded mutation commands. `mkdir` exists but fails closed because Modal's SDK does not expose an explicit mkdir primitive; create directory-like paths through `put`.

## Command surface

Implemented commands:

```bash
uv run mfs version --json
uv run mfs doctor Volumes/modal/PROFILE/ENV --json
uv run mfs cd Volumes/modal/PROFILE/ENV/VOLUME --json
uv run mfs pwd --json
uv run mfs ls Volumes/modal/PROFILE/ENV --limit 20 --json
uv run mfs tree Volumes/modal/PROFILE/ENV/VOLUME --depth 4 --limit 100 --json
uv run mfs stat Volumes/modal/PROFILE/ENV/VOLUME/path --json
uv run mfs cat Volumes/modal/PROFILE/ENV/VOLUME/path --bytes 0:4096 --json
uv run mfs du Volumes/modal/PROFILE/ENV/VOLUME -s --json
uv run mfs find Volumes/modal/PROFILE/ENV/VOLUME --glob "*.json" --json
uv run mfs index Volumes/modal/PROFILE/ENV/VOLUME --store .mfs/index.sqlite --json
uv run mfs grep Volumes/modal/PROFILE/ENV/VOLUME PATTERN --store .mfs/index.sqlite --json
uv run mfs search Volumes/modal/PROFILE/ENV/VOLUME QUERY --lex --store .mfs/index.sqlite --json
uv run mfs manifest Volumes/modal/PROFILE/ENV/VOLUME --jsonl
uv run mfs changed Volumes/modal/PROFILE/ENV/VOLUME --since manifest.jsonl --json
uv run mfs get Volumes/modal/PROFILE/ENV/VOLUME/path ./path --force --json
uv run mfs put ./path Volumes/modal/PROFILE/ENV/VOLUME/path --force --json
uv run mfs rm Volumes/modal/PROFILE/ENV/VOLUME/path --yes --json
uv run mfs cp Volumes/modal/PROFILE/ENV/VOLUME/a Volumes/modal/PROFILE/ENV/VOLUME/b --force --json
uv run mfs mv Volumes/modal/PROFILE/ENV/VOLUME/a Volumes/modal/PROFILE/ENV/VOLUME/b --yes --force --json
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
docs/agents/       engineering-skill repo context
```

## Constraints

- Prefer Python + Click for CLI unless spec changes.
- Prefer `uv_build` packaging.
- All agent-facing commands need `--json` or JSON output mode.
- Remote reads must be bounded by defaults: no surprise full-volume downloads.
- Destructive commands require explicit confirmation flags.
- Modal commit/reload consistency must be visible, not hidden.

## Agent skills

### Issue tracker

Issues and PRDs are tracked as local markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

The repo uses the default five-role triage vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repo with root `CONTEXT.md` and optional root ADRs under `docs/adr/`. See `docs/agents/domain.md`.

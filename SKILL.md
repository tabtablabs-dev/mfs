---
name: mfs
description: Use this skill whenever the user needs to inspect, search, read, index, upload, download, delete, copy, move, mkdir, or create Modal Volumes with the mfs CLI. Trigger for Modal Volume filesystem work, Volumes/modal paths, modal:// URIs, mfs cwd, sidecar indexes, manifests, change detection, PATH_TOO_BROAD, CWD_NOT_SET, or requests to make Modal Volumes feel like a filesystem. Prefer mfs over ad hoc Modal SDK scripts or unbounded modal CLI operations for agent-safe, JSON-friendly remote filesystem work.
---

# mfs

`mfs` is a Modal Volume filesystem/query CLI for agents and operators. Use it when the task is to inspect or carefully mutate Modal Volumes through familiar filesystem-shaped commands without mounting the Volume or writing one-off Modal SDK scripts.

The design target is remote-agent command parity, not POSIX parity: familiar verbs, bounded defaults, stable JSON output, explicit Modal profile/environment addressing, and honest behavior around Modal's remote consistency model.

## First Principles

- Prefer `mfs` for Modal Volume filesystem questions instead of raw SDK snippets, `modal volume` subprocesses, or broad remote crawls.
- Use JSON output for agent work: add `--json` to commands that support it, and use `--jsonl` for manifest streams.
- Address remote data explicitly with `Volumes/modal/PROFILE/ENV/VOLUME/path` or `modal://PROFILE/ENV/VOLUME/path`.
- Do not rely on the shell's active Modal profile/environment to guess remote targets. `PROFILE` and `ENV` belong in the path.
- Treat `mfs cd` as `mfs` application state only. It updates `~/.mfs/state.json`; it cannot change the parent shell's working directory.
- Keep reads and traversal bounded. Use `--limit`, `--depth`, `--bytes`, `--lines`, and `--max-bytes` deliberately.
- Use live commands for source-of-truth checks. The SQLite sidecar index accelerates search and manifests, but Modal remains the source of truth.
- Do not run destructive or overwrite operations unless the user requested that mutation or the current task clearly requires it. When mutation is requested, use the explicit guard flags (`--yes`, `--force`, `--recursive`) and report what was targeted.
- New Modal Volumes must be created as Volumes v2. `mfs mkdir NAME` at an environment root does this; do not introduce v1 creation paths.

## Setup And Access

From a source checkout, prefix examples with `uv run`:

```bash
uv run mfs version --json
uv run modal profile list
uv run mfs doctor Volumes/modal/PROFILE/ENV --json
```

For this user's common workspace, the profile/environment is often:

```bash
uv run mfs doctor Volumes/modal/tabtablabs/main --json
```

If the user specifically asks to activate a Modal profile, use Modal's profile command before running live remote operations:

```bash
uv run modal profile activate tabtablabs
```

`mfs` itself still expects explicit profile/environment path segments even after profile activation.

## Addressing

Primary path syntax:

```text
Volumes/modal/PROFILE/ENV/VOLUME/path/to/file
```

Canonical URI syntax:

```text
modal://PROFILE/ENV/VOLUME/path/to/file
```

Root discovery paths are valid targets:

```text
Volumes/
Volumes/modal
Volumes/modal/PROFILE
Volumes/modal/PROFILE/ENV
```

Relative paths resolve against the active `mfs` virtual cwd:

```bash
uv run mfs cd Volumes/modal/PROFILE/ENV/VOLUME/a/b --json
uv run mfs ls cache --limit 100 --json
uv run mfs cd .. --json
uv run mfs cat /root-file.json --bytes 0:4096 --json
```

Leading `/path` means "from the current Modal Volume root", not the local filesystem root. If cwd is not inside a specific Volume, leading slash targets should fail with `CWD_VOLUME_REQUIRED`.

## Command Recipes

### Discover The Remote Shape

```bash
uv run mfs ls Volumes/ --json
uv run mfs ls Volumes/modal --json
uv run mfs ls Volumes/modal/PROFILE --json
uv run mfs ls Volumes/modal/PROFILE/ENV --limit 50 --json
```

List a Volume root without recursive crawling:

```bash
uv run mfs ls Volumes/modal/PROFILE/ENV/VOLUME --limit 100 --json
```

Use `-a` to include dotfiles such as `.mfskeep`, and `-l` for Modal metadata fields:

```bash
uv run mfs ls Volumes/modal/PROFILE/ENV/VOLUME -a -l --limit 100 --json
```

### Set And Inspect Virtual cwd

```bash
uv run mfs cd Volumes/modal/PROFILE/ENV/VOLUME --json
uv run mfs pwd --json
uv run mfs ls --limit 100 --json
```

Reset cwd to the virtual root:

```bash
uv run mfs cd --json
uv run mfs pwd --json
```

If `mfs ls` returns `CWD_NOT_SET`, either run `mfs cd ...` or provide an explicit target.

### Read Safely

Prefer small reads first:

```bash
uv run mfs stat campaign.json --json
uv run mfs cat campaign.json --bytes 0:4096 --json
uv run mfs cat campaign.json --lines 1:80 --json
```

Raise `--max-bytes` only when needed and explain why:

```bash
uv run mfs cat large.jsonl --bytes 0:131072 --max-bytes 131072 --json
```

### Traverse With Budgets

```bash
uv run mfs tree . --depth 2 --limit 200 --json
uv run mfs du . --depth 4 --limit 1000 --json
uv run mfs du . -s -h --depth 8 --limit 10000 --json
```

If JSON reports `partial: true`, say which budget was hit and narrow the path or raise the budget deliberately.

### Build And Query A Sidecar Index

Use a project-local store when reproducibility matters:

```bash
uv run mfs index . --store .mfs/index.sqlite --max-bytes 65536 --limit 10000 --json
uv run mfs update . --store .mfs/index.sqlite --max-bytes 65536 --limit 10000 --json
```

Query indexed metadata and text:

```bash
uv run mfs find . --glob "*.json" --store .mfs/index.sqlite --json
uv run mfs grep . "created_at" --glob "*.json" --store .mfs/index.sqlite --json
uv run mfs search . "created_at status" --lex --store .mfs/index.sqlite --json
```

Use `update` or a live read before making freshness-sensitive claims.

### Produce Manifests And Detect Changes

```bash
uv run mfs manifest . --limit 10000 --jsonl > manifest.jsonl
uv run mfs changed . --since manifest.jsonl --json
```

Manifests are snapshots of known remote metadata, not locks and not proof that no concurrent writer exists.

### Download And Upload

Download explicit targets:

```bash
uv run mfs get report.json ./report.json --force --json
uv run mfs get dataset/ ./dataset --recursive --force --json
```

Upload explicit files or directories:

```bash
uv run mfs put ./artifact.bin artifact.bin --force --json
uv run mfs put ./exports exports --recursive --force --json
```

Use `--recursive` only for directories. Use `--force` only when overwriting is intended.

### Remove, Copy, Move

Removal requires explicit confirmation:

```bash
uv run mfs rm old-output.json --yes --json
uv run mfs rm old-prefix --recursive --yes --json
```

Copy is same-volume only in the MVP:

```bash
uv run mfs cp a.json b.json --force --json
```

Move is copy-then-remove and requires source removal confirmation:

```bash
uv run mfs mv a.json archive/a.json --force --yes --json
```

Do not describe `mv` as atomic.

### mkdir And Volume Creation

At an environment root, `mkdir NAME` creates a new Modal Volume v2:

```bash
uv run mfs cd Volumes/modal/PROFILE/ENV --json
uv run mfs mkdir public-records --json
```

Inside a Volume, `mkdir path` creates a directory-like prefix by uploading a hidden `.mfskeep` marker because the Modal SDK does not expose an explicit directory mkdir primitive:

```bash
uv run mfs cd Volumes/modal/PROFILE/ENV/VOLUME --json
uv run mfs mkdir nested/path --json
uv run mfs ls nested -a --json
```

Normal `mfs ls` hides `.mfskeep`; use `-a` only when marker visibility matters.

## Error Handling

Read the stable JSON error code first. Report the code, target, and practical next command.

- `CWD_NOT_SET`: set a virtual cwd with `mfs cd ...` or provide an explicit target.
- `CWD_VOLUME_REQUIRED`: cwd is too broad for leading slash resolution; cd into a concrete Volume.
- `PATH_TOO_BROAD`: the Modal path is too broad for safe listing; narrow the prefix before retrying.
- `TARGET_REQUIRED`: provide a target or establish cwd.
- `REMOTE_DEST_EXISTS`: rerun with `--force` only if overwrite is intended.
- `CONFIRMATION_REQUIRED`: rerun with `--yes` only if destructive mutation is intended.
- Adapter/private-proto errors: run `mfs doctor Volumes/modal/PROFILE/ENV --json` and fail closed rather than switching to unbounded reads/listings.

## Response Pattern

When reporting results to the user, include:

- the command or command family used
- the resolved Modal target (`Volumes/...` or `modal://...`)
- relevant safety budget (`--limit`, `--depth`, `--bytes`, `--max-bytes`)
- whether the result was complete, truncated, or partial
- for writes, the explicit guard flags used and the affected path
- for errors, the stable code and the next safe retry

Keep summaries concrete. Do not claim that an index is fresh unless you just ran `index`, `update`, or a live command that proves it.

## Development Notes For This Repo

When editing `mfs` itself, stay aligned with the existing architecture:

- CLI code lives in `src/mfs/cli.py`.
- Path parsing and canonicalization live in `src/mfs/paths.py`.
- Virtual cwd state lives in `src/mfs/state.py`.
- Modal SDK/private-proto calls stay confined to `src/mfs/modal_adapter.py`.
- SQLite sidecar behavior lives in `src/mfs/index.py`.
- Stable JSON errors belong in `src/mfs/errors.py` and `src/mfs/output.py`.

Use the project checks after implementation changes:

```bash
just check
uv build
```

Docs-only changes can usually be verified with:

```bash
git diff --check
```

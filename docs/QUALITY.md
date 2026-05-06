# Quality

## Bar

- Commands are deterministic and scriptable.
- JSON output is stable and tested.
- Destructive behavior is opt-in; v0.0.1 is read-only.
- Remote reads have bounded defaults.
- Modal consistency/staleness is visible where relevant.
- Private/proto Modal adapter paths fail closed if bounded semantics are unavailable.

## Required checks

```bash
uv run ruff check --fix .
uv run ruff format .
uvx pyscn@latest check . --select complexity,deadcode,deps
uv run pytest
uv build
```

## v0.0.1 live smoke checks

Run only when a Modal profile is configured and safe to query:

```bash
uv run mfs doctor Volumes/modal/PROFILE/ENV --json
uv run mfs ls Volumes/ --json
uv run mfs ls Volumes/modal --json
uv run mfs ls Volumes/modal/PROFILE/ENV --limit 1 --json
uv run mfs ls Volumes/modal/PROFILE/ENV/VOLUME --limit 3 --json
uv run mfs stat Volumes/modal/PROFILE/ENV/VOLUME/path/file --json
uv run mfs cat Volumes/modal/PROFILE/ENV/VOLUME/path/file --bytes 0:64 --json
```

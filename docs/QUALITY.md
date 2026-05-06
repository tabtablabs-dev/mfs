# Quality

## Bar

- Commands are deterministic and scriptable.
- JSON output is stable and tested.
- Destructive behavior is opt-in.
- Remote reads have bounded defaults.
- Modal consistency/staleness is visible.

## Planned checks

```bash
ruff check --fix
ruff format
uvx pyscn@latest check . --select complexity,deadcode,deps
pytest
```

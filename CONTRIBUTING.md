# Contributing

Thanks for helping make `mfs` safer and more useful for agent workflows over Modal Volumes.

## Local setup

```bash
uv sync
uv run mfs version
```

## Checks

Run before opening a PR:

```bash
just check
uv build
```

Equivalent:

```bash
uv run ruff check --fix .
uv run ruff format .
uvx pyscn@latest check . --select complexity,deadcode,deps
uv run pytest
uv build
```

## Design rules

- Keep remote operations bounded by default.
- Preserve stable JSON errors for agent branching.
- Do not add unbounded fallbacks when Modal private/proto bounded calls fail.
- Do not print or persist Modal token values.
- Do not mark planned commands as shipped until implemented and tested.

## Modal-dependent changes

Unit tests should not require Modal credentials. If a change needs live Modal validation, document the exact smoke command and keep output free of secrets.

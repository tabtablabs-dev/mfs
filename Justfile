set shell := ["bash", "-cu"]

format:
    uv run ruff format .

lint:
    uv run ruff check --fix .

quality:
    uvx pyscn@latest check . --select complexity,deadcode,deps

test:
    uv run pytest

check: lint format quality test

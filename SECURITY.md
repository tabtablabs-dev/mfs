# Security Policy

## Supported versions

`mfs` is pre-1.0 alpha. Security fixes land on `main` and the latest tagged release line.

## Reporting a vulnerability

Please report vulnerabilities privately to the repository owner/maintainer once a public remote exists. Do not open a public issue containing secrets, tokens, exploit details, or private Modal workspace data.

## Project security stance

- `mfs` must not print Modal token values.
- `mfs` must not persist Modal token values.
- Remote reads/listings must remain bounded by default.
- Broad Modal path failures must fail closed instead of triggering unbounded crawl/download behavior.

See `docs/SECURITY.md` for implementation notes.

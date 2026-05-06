# Security

## Principles

- Do not store Modal tokens or secrets in repo files.
- Avoid indexing likely secret files by default.
- Avoid printing binary or secret-looking content by default.
- Destructive operations require explicit flags.

## Sensitive paths/patterns to skip by default

```text
**/.env
**/.env.*
**/*secret*
**/*credential*
**/*token*
**/id_rsa
**/id_ed25519
```

Open question: should skipped files still appear in metadata manifests with redacted content flags?

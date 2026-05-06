# Security

## Principles

- Do not store Modal tokens or secrets in repo files.
- Do not print Modal token values.
- Avoid indexing likely secret files by default when the index ships.
- Avoid printing binary or secret-looking content by default.
- Destructive operations require explicit flags; v0.0.1 has no write commands.

## v0.0.1 behavior

- `doctor` reports token presence as booleans only.
- Explicit profile credentials are read with `use_env=False` so a path's `PROFILE` segment is not silently redirected by process env.
- `cat` is byte-capped and JSON mode base64-encodes non-UTF-8 content.
- Broad-path Modal failures are surfaced instead of bypassed with unbounded listing.

## Sensitive paths/patterns to skip by default once indexing ships

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

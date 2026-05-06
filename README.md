# mfs

Modal Volume filesystem/query CLI for agents.

`mfs` makes Modal Volumes feel like a bounded remote filesystem without pretending they are POSIX mounts. It gives agents stable JSON commands for discovery, volume listing, safe directory listing, stat, and byte-capped reads.

## Status

The package version is `v0.0.1`. The current worktree implements the MVP command surface from `docs/SPEC.md`.

```text
mfs version [--json]
mfs doctor [TARGET] [--json]
mfs cd [TARGET] [--json]
mfs pwd [--json]
mfs ls [TARGET] [-a] [-l] [--limit N] [--recursive] [--json]
mfs tree [TARGET] [--depth N] [--limit N] [--json]
mfs stat TARGET [--json]
mfs cat TARGET [--bytes START:LEN] [--lines START:END] [--max-bytes N] [--json]
mfs du TARGET [-s] [-h] [--depth N] [--limit N] [--json]
mfs find TARGET --glob GLOB [--size EXPR] [--mtime EXPR] [--json]
mfs index TARGET [--store PATH] [--max-bytes N] [--json]
mfs update TARGET [--store PATH] [--max-bytes N] [--json]
mfs grep TARGET PATTERN [--glob GLOB] [--context N] [--json]
mfs search TARGET QUERY --lex [--json]
mfs manifest TARGET [--jsonl]
mfs changed TARGET --since MANIFEST_OR_INDEX [--json]
mfs get TARGET LOCAL_DEST [--recursive] [--force]
mfs put LOCAL_PATH TARGET [--recursive] [--force]
mfs rm TARGET [--recursive] --yes
mfs cp SRC DST [--recursive] [--force]
mfs mv SRC DST [--force] --yes
mfs mkdir TARGET [--parents]
```

`mfs mkdir` currently fails closed with `UNSUPPORTED_OPERATION` because Modal's SDK does not expose an explicit mkdir primitive. Create directory-like paths by uploading files with `put`.

## Install from source

```bash
git clone <repo-url> mfs
cd mfs
uv sync
uv run mfs version
```

For editable local use:

```bash
uv run mfs doctor --json
```

`mfs` requires a configured Modal profile:

```bash
modal profile list
modal token new
```

## Addressing model

Primary virtual path syntax:

```text
Volumes/modal/PROFILE/ENV/VOLUME/path/to/file
```

Canonical URI syntax, accepted anywhere a target is expected:

```text
modal://PROFILE/ENV/VOLUME/path/to/file
```

Both `PROFILE` and `ENV` are explicit on purpose. v0.0.1 does not silently inherit Modal's active profile or environment for remote paths.

Root discovery:

```bash
mfs ls Volumes/ --json
mfs ls Volumes/modal --json
mfs ls Volumes/modal/tabtablabs --json
mfs ls Volumes/modal/tabtablabs/main --limit 20 --json
```

## Examples

List configured providers:

```bash
mfs ls Volumes/ --json
```

List Modal profiles from local Modal config:

```bash
mfs ls Volumes/modal --json
```

List environments for a profile:

```bash
mfs ls Volumes/modal/PROFILE --json
```

List volumes in an environment:

```bash
mfs ls Volumes/modal/PROFILE/ENV --limit 50 --json
```

List a Volume root without recursive download:

```bash
mfs ls Volumes/modal/PROFILE/ENV/VOLUME --limit 100 --json
```

Stat a file:

```bash
mfs stat Volumes/modal/PROFILE/ENV/VOLUME/path/file.json --json
```

Read the first 4 KiB of a file:

```bash
mfs cat Volumes/modal/PROFILE/ENV/VOLUME/path/file.json --bytes 0:4096 --json
```

## Safety model

Defaults and guardrails:

- No recursive listing unless `--recursive` is explicit.
- Every remote listing is capped by `--limit`.
- Every `cat` is capped by `--max-bytes`.
- `cat --bytes START:LEN` fails if `LEN > --max-bytes`.
- `du`, `tree`, `find`, `index`, `manifest`, and recursive `get` use explicit traversal limits.
- `rm` and `mv` require `--yes`.
- `put`, `cp`, and `mv` require `--force` before overwriting a remote destination.
- `put` requires `--recursive` when the local source is a directory.
- Broad Modal paths can fail with `PATH_TOO_BROAD`; `mfs` reports that as a structured error and tells the agent to narrow the prefix.
- `mfs` does not print Modal token values.

## Modal adapter notes

Modal SDK `1.3.5+` does not expose all bounded operations through public methods. To stay agent-safe, v0.0.1 uses adapter-confined private/proto calls:

- explicit profile credentials via `modal.config.config.get(profile=..., use_env=False)`
- direct private Modal `_Client` per profile
- `VolumeListFiles2/VolumeListFiles(max_entries=...)` for bounded listings
- `VolumeGetFile2(start,len)` for byte-range reads

`mfs doctor --json` reports which adapter path is active.

## JSON errors

Errors use stable machine-readable codes:

```json
{
  "error": {
    "code": "PATH_TOO_BROAD",
    "message": "Path is too broad for Modal to list safely; narrow the prefix",
    "retryable": false,
    "uri": "modal://PROFILE/ENV/VOLUME/path"
  }
}
```

Current codes include:

```text
CONFIRMATION_REQUIRED
CROSS_VOLUME_UNSUPPORTED
CWD_NOT_SET
CWD_VOLUME_REQUIRED
INVALID_TARGET
LOCAL_DEST_EXISTS
LOCAL_NOT_FOUND
MODAL_SDK_UNAVAILABLE
MODAL_PROFILE_NOT_FOUND
MODAL_AUTH_MISSING
MODAL_AUTH_ERROR
RECURSIVE_REQUIRED
REMOTE_NOT_FOUND
REMOTE_DEST_EXISTS
REMOTE_TIMEOUT
PATH_TOO_BROAD
BYTE_LIMIT_EXCEEDED
INVALID_BYTE_RANGE
INVALID_LINE_RANGE
UNSUPPORTED_OPERATION
UNSUPPORTED_SEARCH_MODE
MODAL_ERROR
```

## Development

```bash
just check
```

Equivalent:

```bash
uv run ruff check --fix .
uv run ruff format .
uvx pyscn@latest check . --select complexity,deadcode,deps
uv run pytest
```

Build distributions:

```bash
uv build
```

## License

MIT. See `LICENSE`.

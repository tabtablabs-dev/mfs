# 001: Modal profile adapter + bounded RPCs

## Question

Given an explicit `mfs` path like `Volumes/modal/tabtablabs/main/<volume>/path`, can the adapter use the `tabtablabs` Modal profile without relying on global active-profile state, and can it enforce agent-safe bounded listings / byte reads?

## Approach

- Use `modal profile activate tabtablabs` before running the spike, matching the requested real profile.
- Read Modal credentials for an explicit profile using `modal.config.config.get(profile=..., use_env=False)`.
- Avoid `Client.from_env()` for the adapter path because it is a process singleton.
- Create a private `_Client` with explicit credentials and call Modal's internal async `_VolumeManager.list(..., client=...)` instead of the public synchronicity wrapper.
- Use private/proto RPCs for the two bounded operations missing from public SDK methods:
  - `VolumeListFilesRequest/VolumeListFiles2Request(max_entries=...)`
  - `VolumeGetFile2Request(start=..., len=...)`

## Run

```bash
modal profile activate tabtablabs
uv run --with 'modal==1.3.5' python spikes/001-modal-profile-adapter/main.py \
  --profile tabtablabs \
  --environment main \
  --json
```

The script is read-only. It does not print raw volume names, file paths, signed URLs, tokens, object IDs, or file contents unless `--show-names` is explicitly passed for local debugging.

Sanitized evidence from the live run is in:

```text
spikes/001-modal-profile-adapter/results/tabtablabs-main.sanitized.json
```

## Evidence

Live run against `tabtablabs/main` with `modal==1.3.5`:

- Explicit profile token lookup worked with `use_env=False`.
- Active `MODAL_PROFILE` env was not required.
- Volume discovery found 13 volumes.
- Root listing with `max_entries=3` succeeded on 9 volumes and failed on 4 with `ConflictError: Too many files to list in the path`.
- Successful listing probes used both `v1` and `v2` RPCs.
- Metadata from `VolumeList` reported `v1` for all sampled volumes, but some volumes required the `v2` listing RPC. Do not trust list metadata alone for API selection.
- Byte-range read worked through `VolumeGetFile2Request(start=0, len=64)`:
  - requested length: 64
  - response length: 64
  - downloaded length: 64
  - signed URL count: 1

## Verdict: VALIDATED

### What worked

- Explicit profile-scoped credentials are feasible without relying on the active profile.
- Direct byte-range reads are feasible through Modal proto/private RPCs.
- Bounded listing is feasible for many paths through proto/private `max_entries`.
- The adapter can keep JSON outputs sanitized and avoid exposing names, paths, URLs, tokens, object IDs, or content.

### What did not work cleanly

- Public `Client.from_env()` is a poor fit for path-scoped profiles because it is a process singleton.
- Passing a direct private `_Client` into the public synchronicity wrapper (`Volume.objects.list.aio(..., client=client)`) hung in the spike. Calling the underlying async `_VolumeManager.list(..., client=client)` worked.
- `VolumeList` metadata did not reliably reveal whether a volume needs v1 or v2 file-listing RPCs.
- Some root listings fail as “too many files” even with `max_entries`. `mfs` must not imply POSIX-like guaranteed enumerable directories.

### Surprises

- Trying v2 listing first and falling back to v1 is safer than trusting metadata version from volume discovery.
- Agent safety is not just “set max_entries”; broad paths can still be rejected by Modal and need explicit path-too-broad handling.

### Recommendation for the real build

- Implement a `ModalProfileClient` that resolves explicit profile credentials with `use_env=False` and opens a private `_Client` per `(profile, server_url)`.
- Avoid `Client.from_env()` and public synchronicity wrappers in the adapter core.
- For file listings, try v2 RPC first; if Modal returns an unsupported-version error, fall back to v1.
- Treat `ConflictError: Too many files to list in the path` as a first-class CLI outcome:
  - return structured JSON error
  - tell the agent to narrow the path/prefix
  - do not silently recurse or download
- Make `mfs ls` non-recursive by default, but still expect broad-path failures.
- Make `mfs index` traverse with bounded, non-recursive directory walks and a strict budget, not a single recursive root listing.

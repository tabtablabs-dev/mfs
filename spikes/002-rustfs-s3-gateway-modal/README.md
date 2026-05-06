# 002: RustFS S3 Gateway on Modal Volume v2

## Question

Can one RustFS process run on Modal, expose an S3-compatible endpoint through
`@modal.web_server`, and persist objects into a Modal Volume v2 across container
restarts or deployments?

This is a throwaway spike. It is not production object storage.

## Architecture

```text
boto3 / awscli / S3-compatible client
        |
        v
Modal HTTPS endpoint
        |
        v
RustFS process listening on :9000
        |
        v
Modal Volume v2 mounted at /modal
        |
        v
/modal/rustfs-data
```

RustFS owns `/modal/rustfs-data`. Do not let ComfyUI, Streamlit, notebooks, or
other Modal functions directly edit files inside that path. If later spikes need
direct filesystem workflows, use a separate path such as `/modal/workspace`.

## Files

```text
.
├── .env.example
├── Makefile
├── README.md
├── modal_rustfs_app.py
├── requirements.txt
└── smoke_test.py
```

## Modal Resources

```text
Modal app name: rustfs-s3-gateway-spike
Modal volume name: rustfs-ai-storage
Modal secret name: rustfs-secrets
Mounted volume path: /modal
RustFS data path: /modal/rustfs-data
RustFS API port: 9000
```

The app uses Modal Volume v2:

```python
modal.Volume.from_name(
    "rustfs-ai-storage",
    create_if_missing=True,
    version=2,
)
```

The app sets `max_containers=1`, `min_containers=0`, and
`scaledown_window=900`. The single-container limit is required because this spike
uses one RustFS writer against one Volume data directory.

## Setup

```bash
cd spikes/002-rustfs-s3-gateway-modal
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Or:

```bash
make install
```

## Secret

Create a Modal Secret with credentials. Do not hardcode credentials in
`modal_rustfs_app.py`.

```bash
modal secret create rustfs-secrets \
  RUSTFS_ACCESS_KEY="replace-with-long-random-key" \
  RUSTFS_SECRET_KEY="replace-with-long-random-secret" \
  --force
```

For local smoke tests, export the same values or put them in an uncommitted
`.env` file based on `.env.example`.

## Deploy

Default deploy uses the official RustFS image:

```bash
modal deploy modal_rustfs_app.py
```

If the official image fails because Modal cannot layer Python into it or cannot
run the Python function runtime cleanly, switch to the binary fallback:

```bash
RUSTFS_MODAL_IMAGE_MODE=binary modal deploy modal_rustfs_app.py
```

The binary fallback uses Debian slim, installs `curl`, `unzip`, and
`ca-certificates`, then downloads:

```text
https://dl.rustfs.com/artifacts/rustfs/release/rustfs-linux-x86_64-musl-latest.zip
```

After deploy, copy the Modal endpoint URL from the CLI output:

```text
https://YOUR-MODAL-ENDPOINT.modal.run
```

## Smoke Test

```bash
S3_ENDPOINT_URL="https://YOUR-MODAL-ENDPOINT.modal.run" \
RUSTFS_ACCESS_KEY="replace-with-long-random-key" \
RUSTFS_SECRET_KEY="replace-with-long-random-secret" \
python3 smoke_test.py
```

Important client note: `smoke_test.py` sets botocore
`request_checksum_calculation="when_required"` and
`response_checksum_validation="when_required"`. Without that, current botocore
uses optional checksum streaming/trailer behavior that reaches Modal's
`web_server` proxy as a chunked request. In this spike, that failed before the
request reached RustFS.

The smoke test:

- creates bucket `spike-bucket` if missing
- uploads a random 10 MB object to `smoke/test-10mb.bin`
- stores a SHA256 manifest next to the object
- lists the uploaded object
- downloads it and verifies SHA256
- uploads 100 small files under a run-specific `smoke/small-files/` prefix
- verifies the small-file count is exactly 100

## Persistence Test

Manual flow:

```text
1. Deploy app.
2. Run smoke_test.py.
3. Confirm object upload succeeds.
4. Stop the active app/container, wait for scale-to-zero, or redeploy.
5. Call endpoint again.
6. Run smoke_test.py --verify-existing.
7. Confirm the previously uploaded object still exists and its hash matches.
```

Command:

```bash
S3_ENDPOINT_URL="https://YOUR-MODAL-ENDPOINT.modal.run" \
RUSTFS_ACCESS_KEY="replace-with-long-random-key" \
RUSTFS_SECRET_KEY="replace-with-long-random-secret" \
python3 smoke_test.py --verify-existing
```

## Minimal Benchmark

```bash
S3_ENDPOINT_URL="https://YOUR-MODAL-ENDPOINT.modal.run" \
RUSTFS_ACCESS_KEY="replace-with-long-random-key" \
RUSTFS_SECRET_KEY="replace-with-long-random-secret" \
python3 smoke_test.py --bench
```

Benchmark rows:

```text
operation
object_count
total_mb
elapsed_seconds
mb_per_second
errors
```

Benchmark cases:

- 1 x 100 MB upload
- 1 x 100 MB download
- 100 x 1 MB uploads
- 1,000 x 10 KB uploads

## Known Constraints

- This runs one RustFS process only.
- This is an S3 compatibility adapter over Modal Volume, not a real managed object store.
- Do not use this as customer-facing production storage.
- Do not run multiple RustFS containers against the same `/modal/rustfs-data` path.
- Do not directly edit `/modal/rustfs-data` from ComfyUI, Streamlit, notebooks, or other scripts.
- Modal web endpoints have request timeout behavior that may affect large S3 uploads.
- Modal Volume v2 is beta.
- Modal Volumes have filesystem semantics, not native object-store semantics.
- RustFS single-node single-disk mode is a low-density, non-critical deployment shape, not a production HA design.
- RustFS documentation recommends XFS for storage disks; Modal Volumes do not expose native disk/filesystem tuning.

## Acceptance Criteria

The spike passes if:

- `modal deploy modal_rustfs_app.py` succeeds
- endpoint starts RustFS successfully
- boto3 can connect using S3 SigV4 credentials
- bucket creation succeeds
- upload/list/download succeeds
- SHA256 hash matches after download
- previously uploaded object survives Modal container restart or redeploy
- implementation uses `max_containers=1`
- credentials are only passed through Modal Secret or local environment variables
- README clearly says this is not production object storage

The spike fails if:

- RustFS cannot start reliably on Modal
- RustFS cannot write to the Modal Volume path
- S3 clients cannot complete basic upload/list/download
- objects disappear after container restart
- large-ish object uploads fail due to endpoint timeout or redirect behavior
- the only working version requires multiple RustFS writers against the same Volume path

## Current Verdict

VALIDATED WITH CAVEATS on 2026-05-06.

What worked:

- Modal Secret creation succeeded for `rustfs-secrets`.
- Modal Volume v2 lazy creation via `version=2` deployed.
- The Debian slim binary fallback deployed successfully.
- The endpoint started RustFS at:
  `https://tabtablabs--rustfs-s3-gateway-spike-serve.modal.run`
- boto3 SigV4 path-style bucket creation, upload, list, download, and SHA256
  verification succeeded.
- The persistence check survived redeploy: `smoke/test-10mb.bin` downloaded
  after redeploy and matched SHA256
  `e58901b592ca0358108e66003c0a4678bb43a01bcd1b1d00d9a893291e05bcc6`.

What did not work cleanly:

- The official `rustfs/rustfs:latest` image path failed during Modal deploy.
  Modal built the layered image but then reported that it could not determine
  the installed Python version for the `serve` function image.
- Default botocore upload behavior initially failed with Modal proxy errors:
  `ValueError: chunked can not be set if "Transfer-Encoding: chunked" header is set`.
  RustFS also logged `MissingContentLength` on the failed write path.
- The spike therefore requires explicit botocore checksum settings. AWS CLI and
  other S3-compatible clients still need their own compatibility check.

Benchmark result:

```text
operation          object_count  total_mb  elapsed_seconds  mb_per_second  errors
upload_1x100mb     1             100.00    4.02             24.85          0
download_1x100mb   1             100.00    10.47            9.55           0
upload_100x1mb     100           100.00    33.01            3.03           0
upload_1000x10kb   1000          9.77      249.16           0.04           0
```

Recommendation: continue with caveats.

The core path is viable for one RustFS process over one Modal Volume v2, but do
not treat this as a generic S3 endpoint yet. The next spike should test AWS CLI,
presigned URLs, multipart edge cases, and the planned `/modal/workspace`
coexistence path before wiring ComfyUI, Streamlit, or notebooks around it.

## Sources

- Modal `web_server`: https://modal.com/docs/reference/modal.web_server
- Modal Volumes and Volume v2: https://modal.com/docs/guide/volumes
- Modal Secrets: https://modal.com/docs/guide/secrets
- Modal request timeouts: https://modal.com/docs/guide/webhook-timeouts
- RustFS Docker install: https://docs.rustfs.com/installation/docker/
- RustFS single-node single-disk install: https://docs.rustfs.com/installation/linux/single-node-single-disk.html

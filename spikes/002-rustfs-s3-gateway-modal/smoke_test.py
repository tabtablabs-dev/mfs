"""Smoke and benchmark client for the Modal RustFS gateway spike."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv

DEFAULT_BUCKET = "spike-bucket"
DEFAULT_OBJECT_KEY = "smoke/test-10mb.bin"
DEFAULT_SIZE_MB = 10
SMALL_FILE_COUNT = 100


class SpikeFailure(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--key", default=DEFAULT_OBJECT_KEY)
    parser.add_argument("--size-mb", type=int, default=DEFAULT_SIZE_MB)
    parser.add_argument("--verify-existing", action="store_true")
    parser.add_argument("--bench", action="store_true")
    return parser.parse_args()


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SpikeFailure(f"Missing required environment variable: {name}")
    return value


def s3_client():
    endpoint_url = require_env("S3_ENDPOINT_URL").rstrip("/")
    access_key = require_env("RUSTFS_ACCESS_KEY")
    secret_key = require_env("RUSTFS_SECRET_KEY")

    config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "path"},
        retries={"max_attempts": 3, "mode": "standard"},
        # Modal's web_server proxy currently rejects botocore's optional
        # chunked checksum trailer path before the request reaches RustFS.
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    )

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
        config=config,
    )


def client_error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


def ensure_bucket(client, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
        return
    except ClientError as exc:
        if client_error_code(exc) not in {"404", "NoSuchBucket", "NotFound"}:
            raise

    client.create_bucket(Bucket=bucket)


def random_file(path: Path, size_bytes: int) -> str:
    hasher = hashlib.sha256()
    remaining = size_bytes

    with path.open("wb") as handle:
        while remaining > 0:
            chunk = secrets.token_bytes(min(1024 * 1024, remaining))
            handle.write(chunk)
            hasher.update(chunk)
            remaining -= len(chunk)

    return hasher.hexdigest()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def manifest_key(key: str) -> str:
    return f"{key}.manifest.json"


def upload_main_object(client, bucket: str, key: str, path: Path, sha256: str) -> None:
    client.upload_file(
        str(path),
        bucket,
        key,
        ExtraArgs={"Metadata": {"sha256": sha256}},
    )
    manifest = {"bucket": bucket, "key": key, "sha256": sha256, "size": path.stat().st_size}
    client.put_object(
        Bucket=bucket,
        Key=manifest_key(key),
        Body=json.dumps(manifest, sort_keys=True).encode("utf-8"),
        ContentType="application/json",
    )


def download_and_verify(client, bucket: str, key: str, expected_sha256: str, dest: Path) -> None:
    client.download_file(bucket, key, str(dest))
    actual_sha256 = sha256_file(dest)
    if actual_sha256 != expected_sha256:
        raise SpikeFailure(
            f"SHA256 mismatch for {key}: expected {expected_sha256}, got {actual_sha256}"
        )


def load_remote_manifest(client, bucket: str, key: str) -> dict[str, object]:
    try:
        response = client.get_object(Bucket=bucket, Key=manifest_key(key))
    except ClientError as exc:
        if client_error_code(exc) in {"404", "NoSuchKey", "NotFound"}:
            raise SpikeFailure(f"Missing remote manifest for {key}") from exc
        raise

    return json.loads(response["Body"].read().decode("utf-8"))


def list_key_count(client, bucket: str, prefix: str) -> int:
    paginator = client.get_paginator("list_objects_v2")
    count = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        count += len(page.get("Contents", []))
    return count


def upload_small_files(client, bucket: str, run_id: str) -> str:
    prefix = f"smoke/small-files/{run_id}/"
    for index in range(SMALL_FILE_COUNT):
        body = f"{run_id}:{index}:{secrets.token_hex(8)}\n".encode()
        client.put_object(Bucket=bucket, Key=f"{prefix}{index:03d}.txt", Body=body)
    return prefix


def run_smoke(client, bucket: str, key: str, size_mb: int) -> None:
    ensure_bucket(client, bucket)
    run_id = uuid.uuid4().hex
    size_bytes = size_mb * 1024 * 1024

    with tempfile.TemporaryDirectory(prefix="rustfs-spike-") as tmp:
        tmpdir = Path(tmp)
        source = tmpdir / "source.bin"
        downloaded = tmpdir / "downloaded.bin"

        expected_sha256 = random_file(source, size_bytes)
        upload_main_object(client, bucket, key, source, expected_sha256)
        listed_count = list_key_count(client, bucket, key)
        if listed_count < 1:
            raise SpikeFailure(f"Uploaded object {key} was not returned by list_objects_v2")

        download_and_verify(client, bucket, key, expected_sha256, downloaded)

        small_prefix = upload_small_files(client, bucket, run_id)
        small_count = list_key_count(client, bucket, small_prefix)
        if small_count != SMALL_FILE_COUNT:
            raise SpikeFailure(
                f"Expected {SMALL_FILE_COUNT} small files under {small_prefix}, got {small_count}"
            )

    print("PASS smoke")
    print(f"bucket={bucket}")
    print(f"main_object={key}")
    print(f"main_object_mb={size_mb}")
    print(f"main_object_sha256={expected_sha256}")
    print(f"small_files_prefix={small_prefix}")
    print(f"small_files_count={SMALL_FILE_COUNT}")


def run_verify_existing(client, bucket: str, key: str) -> None:
    ensure_bucket(client, bucket)
    manifest = load_remote_manifest(client, bucket, key)
    expected_sha256 = str(manifest["sha256"])

    with tempfile.TemporaryDirectory(prefix="rustfs-spike-verify-") as tmp:
        download_and_verify(client, bucket, key, expected_sha256, Path(tmp) / "downloaded.bin")

    print("PASS verify-existing")
    print(f"bucket={bucket}")
    print(f"main_object={key}")
    print(f"main_object_sha256={expected_sha256}")


def timed_operation(
    operation: str,
    object_count: int,
    total_mb: float,
    func: Callable[[], None],
) -> dict[str, object]:
    started = time.perf_counter()
    errors = 0
    try:
        func()
    except Exception:
        errors = 1
        raise
    finally:
        elapsed = time.perf_counter() - started
        mb_per_second = total_mb / elapsed if elapsed else 0.0
        print(
            f"{operation}\t{object_count}\t{total_mb:.2f}\t"
            f"{elapsed:.2f}\t{mb_per_second:.2f}\t{errors}"
        )

    return {
        "operation": operation,
        "object_count": object_count,
        "total_mb": total_mb,
        "elapsed_seconds": elapsed,
        "mb_per_second": mb_per_second,
        "errors": errors,
    }


def upload_repeated_files(
    client,
    bucket: str,
    prefix: str,
    count: int,
    size_bytes: int,
) -> None:
    payload = secrets.token_bytes(size_bytes)
    for index in range(count):
        client.put_object(Bucket=bucket, Key=f"{prefix}{index:04d}.bin", Body=payload)


def run_bench(client, bucket: str) -> None:
    ensure_bucket(client, bucket)
    run_id = uuid.uuid4().hex
    prefix = f"bench/{run_id}/"

    print("operation\tobject_count\ttotal_mb\telapsed_seconds\tmb_per_second\terrors")

    with tempfile.TemporaryDirectory(prefix="rustfs-spike-bench-") as tmp:
        tmpdir = Path(tmp)
        source_100mb = tmpdir / "bench-100mb.bin"
        download_100mb = tmpdir / "bench-100mb.downloaded.bin"
        random_file(source_100mb, 100 * 1024 * 1024)

        timed_operation(
            "upload_1x100mb",
            1,
            100.0,
            lambda: client.upload_file(str(source_100mb), bucket, f"{prefix}100mb.bin"),
        )
        timed_operation(
            "download_1x100mb",
            1,
            100.0,
            lambda: client.download_file(bucket, f"{prefix}100mb.bin", str(download_100mb)),
        )

    timed_operation(
        "upload_100x1mb",
        100,
        100.0,
        lambda: upload_repeated_files(client, bucket, f"{prefix}1mb/", 100, 1024 * 1024),
    )
    timed_operation(
        "upload_1000x10kb",
        1000,
        9.77,
        lambda: upload_repeated_files(client, bucket, f"{prefix}10kb/", 1000, 10 * 1024),
    )


def main() -> int:
    load_dotenv()
    args = parse_args()

    try:
        client = s3_client()
        if args.bench:
            run_bench(client, args.bucket)
        elif args.verify_existing:
            run_verify_existing(client, args.bucket, args.key)
        else:
            run_smoke(client, args.bucket, args.key, args.size_mb)
    except Exception as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

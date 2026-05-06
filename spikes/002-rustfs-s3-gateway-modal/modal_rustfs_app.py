"""PROTOTYPE: RustFS S3 gateway on a Modal Volume v2.

Question: can one RustFS process run behind a Modal web endpoint and persist
S3 objects into a Modal Volume v2 across container restarts?
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import modal

APP_NAME = "rustfs-s3-gateway-spike"
VOLUME_NAME = "rustfs-ai-storage"
SECRET_NAME = "rustfs-secrets"

MOUNT_PATH = "/modal"
DATA_DIR = f"{MOUNT_PATH}/rustfs-data"
RUSTFS_PORT = 9000

RUSTFS_DOWNLOAD_URL = (
    "https://dl.rustfs.com/artifacts/rustfs/release/rustfs-linux-x86_64-musl-latest.zip"
)

app = modal.App(APP_NAME)

volume = modal.Volume.from_name(
    VOLUME_NAME,
    create_if_missing=True,
    version=2,
)


def official_image() -> modal.Image:
    return modal.Image.from_registry(
        "rustfs/rustfs:latest",
        add_python="3.12",
    )


def binary_fallback_image() -> modal.Image:
    return (
        modal.Image.debian_slim(python_version="3.12")
        .apt_install("ca-certificates", "curl", "unzip")
        .run_commands(
            "rm -rf /tmp/rustfs-install && mkdir -p /tmp/rustfs-install",
            f"curl -fL {RUSTFS_DOWNLOAD_URL} -o /tmp/rustfs-install/rustfs.zip",
            "unzip /tmp/rustfs-install/rustfs.zip -d /tmp/rustfs-install",
            (
                "find /tmp/rustfs-install -type f -name rustfs -perm /111 "
                "-exec install -m 0755 {} /usr/local/bin/rustfs \\; -quit"
            ),
            "test -x /usr/local/bin/rustfs",
        )
    )


IMAGE_MODE = os.environ.get("RUSTFS_MODAL_IMAGE_MODE", "official").strip().lower()
if IMAGE_MODE == "binary":
    image = binary_fallback_image()
elif IMAGE_MODE == "official":
    image = official_image()
else:
    raise ValueError("RUSTFS_MODAL_IMAGE_MODE must be 'official' or 'binary'")


def wait_for_port(host: str, port: int, timeout_s: int = 90) -> None:
    deadline = time.time() + timeout_s

    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.5)

    raise RuntimeError(f"RustFS did not start on {host}:{port}")


def find_rustfs_binary() -> str:
    found = shutil.which("rustfs")
    if found:
        return found

    for candidate in ("/usr/local/bin/rustfs", "/usr/bin/rustfs", "/rustfs"):
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate

    raise RuntimeError("Could not find an executable rustfs binary in the image")


@app.function(
    image=image,
    volumes={MOUNT_PATH: volume},
    secrets=[modal.Secret.from_name(SECRET_NAME)],
    max_containers=1,
    min_containers=0,
    scaledown_window=900,
    cpu=1.0,
    memory=4096,
    timeout=24 * 60 * 60,
)
@modal.concurrent(max_inputs=32, target_inputs=8)
@modal.web_server(port=RUSTFS_PORT, startup_timeout=120)
def serve():
    access_key = os.environ["RUSTFS_ACCESS_KEY"]
    secret_key = os.environ["RUSTFS_SECRET_KEY"]

    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "RUSTFS_ACCESS_KEY": access_key,
            "RUSTFS_SECRET_KEY": secret_key,
            "RUSTFS_ADDRESS": f":{RUSTFS_PORT}",
            "RUSTFS_CONSOLE_ENABLE": "false",
        }
    )

    cmd = [find_rustfs_binary(), DATA_DIR]
    process = subprocess.Popen(cmd, env=env)

    try:
        wait_for_port("127.0.0.1", RUSTFS_PORT, timeout_s=90)
    except Exception:
        process.terminate()
        raise

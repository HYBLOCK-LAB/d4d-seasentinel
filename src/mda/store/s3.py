from __future__ import annotations

import os
import subprocess

from dotenv import load_dotenv

from mda.paths import lake_dir, repo_root

_env_loaded = False


def _env() -> dict:
    global _env_loaded
    if not _env_loaded:
        load_dotenv(repo_root() / ".env")
        _env_loaded = True
    endpoint = os.environ.get("S3_ENDPOINT")
    bucket = os.environ.get("S3_BUCKET")
    access = os.environ.get("S3_ACCESS_KEY")
    secret = os.environ.get("S3_SECRET_KEY")
    if not (endpoint and bucket and access and secret):
        raise RuntimeError("S3_ENDPOINT / S3_BUCKET / S3_ACCESS_KEY / S3_SECRET_KEY not set")
    return {"endpoint": endpoint, "bucket": bucket, "access": access, "secret": secret}


def _run(args: list[str], env: dict) -> str:
    proc_env = {
        **os.environ,
        "AWS_ACCESS_KEY_ID": env["access"],
        "AWS_SECRET_ACCESS_KEY": env["secret"],
        "AWS_EC2_METADATA_DISABLED": "true",
    }
    result = subprocess.run(
        ["aws", *args, "--endpoint-url", env["endpoint"]],
        env=proc_env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"aws {' '.join(args)} failed: {result.stderr.strip()[:300]}")
    return result.stdout


def sync_lake(prefix: str = "lake") -> dict:
    env = _env()
    local = lake_dir()
    local.mkdir(parents=True, exist_ok=True)
    out = _run(["s3", "sync", str(local), f"s3://{env['bucket']}/{prefix}"], env)
    uploaded = [line for line in out.splitlines() if line.startswith("upload:")]
    return {"bucket": env["bucket"], "prefix": prefix, "uploaded": len(uploaded)}


def upload_file(local_path: str, key: str) -> str:
    env = _env()
    _run(["s3", "cp", local_path, f"s3://{env['bucket']}/{key}"], env)
    cdn = os.environ.get("S3_CDN", env["endpoint"]).rstrip("/")
    return f"{cdn}/{env['bucket']}/{key}"

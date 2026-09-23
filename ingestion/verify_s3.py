"""
Verify that the S3 lake matches the local data directory.

Answers the only question that matters after an upload: "did all of it actually
get there?" A truncated multipart upload or a forgotten table folder produces a
COPY INTO that succeeds with quietly wrong row counts — exactly the kind of
failure that is expensive to find later.

Compares, in both directions:
  * files present locally but missing in S3
  * objects present in S3 but not locally (usually a stale earlier load)
  * files whose byte size differs

Exits non-zero when anything mismatches, so it is safe to run as a pipeline gate
or in CI.

Usage:
    python ingestion/verify_s3.py
    python ingestion/verify_s3.py --table orders
    python ingestion/verify_s3.py --allow-extra     # tolerate stale remote files
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_SOURCE = PROJECT_ROOT / "data" / "raw"


def human_bytes(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:,.1f} {unit}"
        size /= 1024
    return f"{size:,.1f} TB"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare local data/raw with s3://<bucket>/raw/")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--bucket", default=os.getenv("S3_BUCKET"))
    parser.add_argument("--prefix", default="raw/")
    parser.add_argument("--table", action="append", default=None)
    parser.add_argument("--profile", default=os.getenv("AWS_PROFILE") or None)
    parser.add_argument("--region", default=os.getenv("AWS_REGION") or None)
    parser.add_argument(
        "--allow-extra",
        action="store_true",
        help="Do not fail on objects that exist in S3 but not locally.",
    )
    return parser.parse_args()


def list_local(source: Path, tables: list[str] | None) -> dict[str, int]:
    if not source.is_dir():
        raise SystemExit(f"error: {source} does not exist.")

    found = {}
    for path in sorted(source.rglob("*.csv")):
        parts = path.relative_to(source).parts
        if tables and parts[0].lower() not in {t.lower() for t in tables}:
            continue
        found[path.relative_to(source).as_posix()] = path.stat().st_size
    return found


def list_remote(client, bucket: str, prefix: str) -> dict[str, int]:
    remote: dict[str, int] = {}
    paginator = client.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix.rstrip("/") + "/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            # A zero-byte key ending in "/" is a folder placeholder, not data.
            if key.endswith("/"):
                continue
            remote[key[len(prefix.rstrip("/")) + 1 :]] = obj["Size"]

    return remote


def main() -> int:
    args = parse_args()

    if not args.bucket:
        raise SystemExit("error: no bucket. Pass --bucket, or set S3_BUCKET in your environment/.env.")

    local = list_local(args.source, args.table)

    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        remote = list_remote(session.client("s3"), args.bucket, args.prefix)
    except (BotoCoreError, ClientError) as exc:
        print(f"error: could not list s3://{args.bucket}/{args.prefix} — {exc}", file=sys.stderr)
        return 1

    missing = sorted(set(local) - set(remote))
    extra = sorted(set(remote) - set(local))
    size_mismatch = sorted(
        rel for rel in set(local) & set(remote) if local[rel] != remote[rel]
    )

    print(f"Local : {args.source}  ({len(local)} file(s), {human_bytes(sum(local.values()))})")
    print(f"Remote: s3://{args.bucket}/{args.prefix}  ({len(remote)} object(s), {human_bytes(sum(remote.values()))})")
    print()

    for rel in missing:
        print(f"  MISSING IN S3  {rel}  (local {human_bytes(local[rel])})")
    for rel in extra:
        print(f"  EXTRA IN S3    {rel}  (remote {human_bytes(remote[rel])})")
    for rel in size_mismatch:
        print(f"  SIZE MISMATCH  {rel}  local {human_bytes(local[rel])} vs remote {human_bytes(remote[rel])}")

    problems = len(missing) + len(size_mismatch) + (0 if args.allow_extra else len(extra))

    if problems == 0:
        matched = len(set(local) & set(remote))
        print(f"OK — {matched} file(s) match exactly.")
        return 0

    print(f"\n{problems} problem(s) found. Re-run: python ingestion/upload_to_s3.py", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

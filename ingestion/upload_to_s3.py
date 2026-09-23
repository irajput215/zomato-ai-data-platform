"""
Upload the generated CSVs to the S3 data lake.

    data/raw/<table>/<table>.csv   ->   s3://<BUCKET>/raw/<table>/<table>.csv

The local directory tree mirrors the S3 layout exactly, so this script is a
straight recursive upload with no naming rules to remember — whatever you drop
under data/raw/ ends up under raw/ in the bucket, at the same relative path.

Files here are gigabytes, so uploads go through boto3's managed multipart
transfer (concurrency + retries handled for you) rather than a single PUT that
would time out on a 2 GB orders.csv.

Usage:
    # see exactly what would happen, touching nothing
    python ingestion/upload_to_s3.py --dry-run

    python ingestion/upload_to_s3.py
    python ingestion/upload_to_s3.py --table orders --table order_items
    python ingestion/upload_to_s3.py --bucket my-bucket --prefix raw/
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    parser = argparse.ArgumentParser(
        description="Upload data/raw/**/*.csv to s3://<bucket>/raw/",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"Local directory to sync (default: {DEFAULT_SOURCE}).",
    )
    parser.add_argument(
        "--bucket",
        default=os.getenv("S3_BUCKET"),
        help="Target bucket (default: S3_BUCKET from the environment).",
    )
    parser.add_argument(
        "--prefix", default="raw/", help="Key prefix inside the bucket (default: raw/)."
    )
    parser.add_argument(
        "--table",
        action="append",
        default=None,
        help="Upload only this table folder. Repeatable, e.g. --table orders --table reviews.",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("AWS_PROFILE") or None,
        help="AWS profile name (default: AWS_PROFILE, else the default chain).",
    )
    parser.add_argument(
        "--region", default=os.getenv("AWS_REGION") or None, help="AWS region."
    )
    parser.add_argument(
        "--workers", type=int, default=4, help="Concurrent file uploads (default: 4)."
    )
    parser.add_argument(
        "--storage-class",
        default="STANDARD",
        help="S3 storage class (default: STANDARD; try INTELLIGENT_TIERING for cheap archives).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the uploads that would happen and exit without touching S3.",
    )
    return parser.parse_args()


def discover_files(source: Path, tables: list[str] | None) -> list[Path]:
    if not source.is_dir():
        raise SystemExit(
            f"error: {source} does not exist.\n"
            f"Generate the data first:\n"
            f"    python data/generator/generate_dimensions.py\n"
            f"    python data/generator/generate_facts.py"
        )

    files = sorted(p for p in source.rglob("*") if p.is_file() and p.suffix == ".csv")

    if tables:
        wanted = {t.strip().lower() for t in tables}
        files = [p for p in files if p.relative_to(source).parts[0].lower() in wanted]

    return files


def upload_one(client, path: Path, source: Path, bucket: str, prefix: str, storage_class: str) -> tuple[Path, int]:
    relative = path.relative_to(source).as_posix()
    key = f"{prefix.rstrip('/')}/{relative}"
    size = path.stat().st_size

    client.upload_file(
        str(path),
        bucket,
        key,
        ExtraArgs={"ContentType": "text/csv", "StorageClass": storage_class},
    )
    return path, size


def main() -> int:
    args = parse_args()

    if not args.bucket and not args.dry_run:
        raise SystemExit(
            "error: no bucket. Pass --bucket, or set S3_BUCKET in your environment/.env."
        )

    try:
        files = discover_files(args.source, args.table)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1

    if not files:
        print(f"No CSV files found under {args.source}", file=sys.stderr)
        return 1

    total_bytes = sum(p.stat().st_size for p in files)

    print(f"Source : {args.source}")
    print(f"Target : s3://{args.bucket}/{args.prefix.rstrip('/')}/")
    print(f"Files  : {len(files)}  ({human_bytes(total_bytes)})")
    print()

    for path in files:
        print(f"  {path.relative_to(args.source).as_posix():<45} {human_bytes(path.stat().st_size):>12}")

    if args.dry_run:
        print("\nDry run — nothing was uploaded.")
        return 0

    print()
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    client = session.client("s3")

    uploaded = 0
    failed: list[tuple[Path, str]] = []

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(
                upload_one, client, path, args.source, args.bucket, args.prefix, args.storage_class
            ): path
            for path in files
        }
        for future in as_completed(futures):
            path = futures[future]
            try:
                _, size = future.result()
            except (BotoCoreError, ClientError, OSError) as exc:
                failed.append((path, str(exc)))
                print(f"  FAILED  {path.name}: {exc}", file=sys.stderr)
                continue

            uploaded += 1
            print(f"  ok  {path.relative_to(args.source).as_posix()}  ({human_bytes(size)})")

    print(f"\nUploaded {uploaded}/{len(files)} file(s).")

    if failed:
        print(f"\n{len(failed)} upload(s) failed. Re-run to retry — completed files are simply overwritten.", file=sys.stderr)
        return 1

    print("\nNext: load the tables into Snowflake with snowflake/05_copy_into.sql,")
    print("or just trigger the `zomato_batch` Airflow DAG.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

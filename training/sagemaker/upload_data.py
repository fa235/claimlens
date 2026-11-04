"""
Upload Training Data to S3
===========================
Uploads the processed CarDD dataset from data/processed/ to S3
so SageMaker can access it during training.

Run this ONCE after prepare_dataset.py and before launch_training.py.

S3 structure created:
  s3://<bucket>/claimlens/training-data/
    train/
      images/  ← JPEG images
      labels/  ← YOLOv8 .txt label files
    val/
      images/
      labels/

Usage:
    export S3_BUCKET=your-claimlens-bucket
    python sagemaker/upload_data.py

    # Specify bucket directly
    python sagemaker/upload_data.py --bucket your-claimlens-bucket

    # Dry run (shows what would be uploaded, no actual upload)
    python sagemaker/upload_data.py --dry-run
"""

import argparse
import os
import sys
from pathlib import Path

try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
    from tqdm import tqdm
except ImportError:
    print("Missing dependencies. Run:  pip install -r sagemaker/requirements_launcher.txt")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass


PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
DEFAULT_PREFIX = "claimlens/training-data"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def count_files(directory: Path) -> int:
    return sum(1 for _ in directory.rglob("*") if _.is_file())


def upload_directory(
    s3_client,
    local_dir: Path,
    bucket: str,
    s3_prefix: str,
    dry_run: bool = False,
) -> int:
    """
    Recursively uploads a local directory to S3.
    Returns number of files uploaded.
    """
    files = [f for f in local_dir.rglob("*") if f.is_file()]
    if not files:
        print(f"  [upload] WARNING: No files found in {local_dir}")
        return 0

    uploaded = 0
    for local_path in tqdm(files, desc=local_dir.name, unit="file"):
        # Build S3 key: prefix/relative_path
        relative = local_path.relative_to(local_dir.parent)
        s3_key   = f"{s3_prefix}/{relative}".replace("\\", "/")

        if dry_run:
            print(f"  [dry-run] Would upload: {local_path} → s3://{bucket}/{s3_key}")
        else:
            try:
                s3_client.upload_file(
                    str(local_path),
                    bucket,
                    s3_key,
                    ExtraArgs={"StorageClass": "STANDARD"},
                )
                uploaded += 1
            except ClientError as e:
                print(f"  [upload] ERROR uploading {local_path}: {e}")

    return uploaded


def verify_bucket_access(s3_client, bucket: str) -> None:
    """Checks bucket exists and credentials work before starting upload."""
    try:
        s3_client.head_bucket(Bucket=bucket)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "404":
            print(f"""
[upload] ERROR: Bucket '{bucket}' does not exist.

Create it first:
    aws s3 mb s3://{bucket} --region us-east-1
""")
        elif code == "403":
            print(f"[upload] ERROR: Access denied to bucket '{bucket}'. Check your IAM permissions.")
        else:
            print(f"[upload] ERROR: {e}")
        sys.exit(1)
    except NoCredentialsError:
        print("""
[upload] ERROR: AWS credentials not found.

Configure them with:
    aws configure
or set environment variables:
    export AWS_ACCESS_KEY_ID=...
    export AWS_SECRET_ACCESS_KEY=...
    export AWS_REGION=us-east-1
""")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Upload processed CarDD dataset to S3 for SageMaker training."
    )
    parser.add_argument(
        "--bucket", default=os.environ.get("S3_BUCKET", ""),
        help="S3 bucket name (or set S3_BUCKET env var)",
    )
    parser.add_argument(
        "--prefix", default=os.environ.get("S3_DATA_PREFIX", DEFAULT_PREFIX),
        help=f"S3 key prefix (default: {DEFAULT_PREFIX})",
    )
    parser.add_argument(
        "--region", default=os.environ.get("AWS_REGION", "us-east-1"),
    )
    parser.add_argument(
        "--data-dir", default=str(PROCESSED_DIR),
        help="Local processed data directory (default: data/processed/)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be uploaded without actually uploading",
    )
    args = parser.parse_args()

    if not args.bucket:
        print("[upload] ERROR: --bucket is required. Set S3_BUCKET or pass --bucket.")
        sys.exit(1)

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"[upload] ERROR: Data directory not found: {data_dir}")
        print("[upload] Run prepare_dataset.py first.")
        sys.exit(1)

    s3 = boto3.client("s3", region_name=args.region)

    if not args.dry_run:
        verify_bucket_access(s3, args.bucket)

    # Count total files
    total_files = count_files(data_dir)
    print(f"""
[upload] ── Upload Configuration ───────────────────────────
  Local data   : {data_dir}
  Total files  : {total_files}
  Destination  : s3://{args.bucket}/{args.prefix}
  Dry run      : {args.dry_run}
─────────────────────────────────────────────────────────────
""")

    splits = [
        ("images/train",  "train/images"),
        ("labels/train",  "train/labels"),
        ("images/val",    "val/images"),
        ("labels/val",    "val/labels"),
    ]

    total_uploaded = 0
    for local_sub, s3_sub in splits:
        local_path = data_dir / local_sub.replace("/", os.sep)
        if not local_path.exists():
            print(f"[upload] Skipping {local_sub} — not found")
            continue

        file_count = count_files(local_path)
        print(f"[upload] Uploading {local_sub} ({file_count} files)…")

        uploaded = upload_directory(
            s3_client=s3,
            local_dir=local_path,
            bucket=args.bucket,
            s3_prefix=f"{args.prefix}/{s3_sub}",
            dry_run=args.dry_run,
        )
        total_uploaded += uploaded

    action = "Would upload" if args.dry_run else "Uploaded"
    print(f"""
[upload] ── Done ────────────────────────────────────────────
  {action} : {total_uploaded} files
  S3 path  : s3://{args.bucket}/{args.prefix}

Next step:
  python sagemaker/launch_training.py --bucket {args.bucket}
─────────────────────────────────────────────────────────────
""")


if __name__ == "__main__":
    main()

"""
Export Weights from S3 to Backend
===================================
After a SageMaker training job completes, this script:
  1. Downloads model.tar.gz from S3
  2. Extracts best.pt
  3. Copies it to backend/weights/damage_detector.pt
  4. Updates YOLO_WEIGHTS in backend/.env

Usage:
    python sagemaker/export_from_s3.py --job-name claimlens-yolov8-20241029-120000 --bucket your-bucket

    # Or point directly at the S3 path
    python sagemaker/export_from_s3.py \
      --s3-path s3://your-bucket/claimlens/training-output/claimlens-yolov8-20241029-120000/output/model.tar.gz
"""

import argparse
import json
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("Missing dependencies. Run:  pip install -r sagemaker/requirements_launcher.txt")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass


BACKEND_WEIGHTS_DIR = Path(__file__).parent.parent.parent / "backend" / "weights"
BACKEND_ENV_FILE    = Path(__file__).parent.parent.parent / "backend" / ".env"
DEFAULT_OUTPUT_PREFIX = "claimlens/training-output"


def get_s3_path(args) -> tuple[str, str]:
    """Returns (bucket, key) for the model.tar.gz artifact."""
    if args.s3_path:
        # Parse s3://bucket/key
        parts = args.s3_path.replace("s3://", "").split("/", 1)
        return parts[0], parts[1]

    if not args.job_name:
        print("[export] ERROR: Provide --job-name or --s3-path")
        sys.exit(1)

    bucket = args.bucket or os.environ.get("S3_BUCKET", "")
    if not bucket:
        print("[export] ERROR: --bucket is required (or set S3_BUCKET)")
        sys.exit(1)

    key = f"{DEFAULT_OUTPUT_PREFIX}/{args.job_name}/output/model.tar.gz"
    return bucket, key


def download_and_extract(bucket: str, key: str, region: str) -> Path:
    """Downloads model.tar.gz from S3 and extracts best.pt. Returns its path."""
    s3 = boto3.client("s3", region_name=region)

    print(f"[export] Downloading s3://{bucket}/{key} …")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path     = Path(tmp)
        archive_path = tmp_path / "model.tar.gz"
        extract_dir  = tmp_path / "model"
        extract_dir.mkdir()

        try:
            s3.download_file(bucket, key, str(archive_path))
        except ClientError as e:
            print(f"[export] ERROR: Could not download from S3: {e}")
            print(f"[export] Check the job name and bucket are correct.")
            sys.exit(1)

        print(f"[export] Extracting archive…")
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(extract_dir)

        # Find best.pt inside the extracted archive
        candidates = list(extract_dir.rglob("best.pt"))
        if not candidates:
            print(f"[export] ERROR: best.pt not found in archive. Contents:")
            for f in extract_dir.rglob("*"):
                print(f"  {f}")
            sys.exit(1)

        best_pt_src = candidates[0]
        print(f"[export] Found: {best_pt_src}")

        # Copy to backend/weights/
        BACKEND_WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
        dest = BACKEND_WEIGHTS_DIR / "damage_detector.pt"
        shutil.copy2(best_pt_src, dest)
        print(f"[export] ✓ Copied → {dest}")

        # Also copy metrics.json if present
        metrics_candidates = list(extract_dir.rglob("metrics.json"))
        if metrics_candidates:
            metrics_dest = BACKEND_WEIGHTS_DIR / "metrics.json"
            shutil.copy2(metrics_candidates[0], metrics_dest)
            with open(metrics_dest) as f:
                metrics = json.load(f)
            print(f"[export] ✓ Metrics: mAP50={metrics.get('mAP50', 'N/A')}")

        return dest


def update_env_file() -> None:
    """Sets YOLO_WEIGHTS=weights/damage_detector.pt in backend/.env."""
    env_example = BACKEND_ENV_FILE.parent / ".env.example"

    if not BACKEND_ENV_FILE.exists():
        if env_example.exists():
            shutil.copy2(env_example, BACKEND_ENV_FILE)
        else:
            BACKEND_ENV_FILE.write_text("")

    lines  = BACKEND_ENV_FILE.read_text().splitlines()
    new_lines = []
    updated   = False

    for line in lines:
        if line.startswith("YOLO_WEIGHTS="):
            new_lines.append("YOLO_WEIGHTS=weights/damage_detector.pt")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append("YOLO_WEIGHTS=weights/damage_detector.pt")

    BACKEND_ENV_FILE.write_text("\n".join(new_lines) + "\n")
    print(f"[export] ✓ Updated YOLO_WEIGHTS in {BACKEND_ENV_FILE}")


def main():
    parser = argparse.ArgumentParser(
        description="Download trained weights from S3 and deploy to backend."
    )
    parser.add_argument("--job-name",  type=str, default=None,
                        help="SageMaker job name (e.g. claimlens-yolov8-20241029-120000)")
    parser.add_argument("--bucket",    type=str, default=os.environ.get("S3_BUCKET", ""),
                        help="S3 bucket name")
    parser.add_argument("--s3-path",   type=str, default=None,
                        help="Full S3 path to model.tar.gz (alternative to --job-name)")
    parser.add_argument("--region",    type=str, default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--no-env-update", action="store_true",
                        help="Skip updating YOLO_WEIGHTS in backend/.env")
    args = parser.parse_args()

    bucket, key = get_s3_path(args)
    dest = download_and_extract(bucket, key, args.region)

    if not args.no_env_update:
        update_env_file()

    print(f"""
[export] ── Done ────────────────────────────────────────────
  Weights deployed : {dest}

  Restart backend to load new weights:
    docker-compose restart backend
─────────────────────────────────────────────────────────────
""")


if __name__ == "__main__":
    main()

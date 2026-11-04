"""
SageMaker Training Job Launcher
================================
Run this locally to kick off a training job on AWS SageMaker.

What it does:
  1. Reads your AWS credentials and config from environment / .env
  2. Submits a SageMaker training job using the PyTorch managed container
  3. Streams logs to your terminal while the job runs
  4. Prints the S3 path of best.pt when done

Prerequisites:
  - AWS credentials configured (aws configure or environment variables)
  - IAM role with SageMaker + S3 permissions (see sagemaker/iam_policy.json)
  - Training data already uploaded to S3 (run upload_data.py first)

Usage:
    python sagemaker/launch_training.py

    # Override hyperparameters
    python sagemaker/launch_training.py --epochs 100 --model yolov8m.pt

    # Use a different instance type
    python sagemaker/launch_training.py --instance ml.g5.xlarge
"""

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import boto3
    import sagemaker
    from sagemaker.pytorch import PyTorch
except ImportError:
    print("Missing dependencies. Run:  pip install -r sagemaker/requirements_launcher.txt")
    sys.exit(1)

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Configuration — override via CLI or environment variables
# ---------------------------------------------------------------------------

DEFAULTS = {
    # AWS
    "region":          os.environ.get("AWS_REGION", "us-east-1"),
    "role_arn":        os.environ.get("SAGEMAKER_ROLE_ARN", ""),
    "s3_bucket":       os.environ.get("S3_BUCKET", ""),
    "s3_prefix":       os.environ.get("S3_DATA_PREFIX", "claimlens/training-data"),

    # Instance
    "instance_type":   "ml.g4dn.xlarge",   # NVIDIA T4, ~$0.74/hr
    "instance_count":  1,
    "volume_size_gb":  30,                  # EBS volume for data + model

    # Hyperparameters
    "model":           "yolov8s.pt",
    "epochs":          50,
    "batch":           16,
    "imgsz":           640,
    "optimizer":       "AdamW",
    "lr0":             0.001,
    "lrf":             0.01,
    "warmup_epochs":   3,
    "weight_decay":    0.0005,
    "patience":        20,
    "mosaic":          1.0,
    "mixup":           0.1,
    "fliplr":          0.5,
    "degrees":         5.0,
}

# PyTorch version installed in the SageMaker managed container
PYTORCH_VERSION  = "2.1"
PYTHON_VERSION   = "py310"
TRANSFORMERS_VERSION = "4.36.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def validate_config(args) -> None:
    """Fail early with helpful messages if config is missing."""
    if not args.role_arn:
        print("""
[launch] ERROR: SAGEMAKER_ROLE_ARN is not set.

Create an IAM role for SageMaker (see sagemaker/iam_policy.json), then:
    export SAGEMAKER_ROLE_ARN=arn:aws:iam::123456789:role/ClaimLensSageMakerRole
or add it to sagemaker/.env
""")
        sys.exit(1)

    if not args.s3_bucket:
        print("""
[launch] ERROR: S3_BUCKET is not set.

Create an S3 bucket for training data, then:
    export S3_BUCKET=your-claimlens-bucket
or add it to sagemaker/.env
""")
        sys.exit(1)


def get_data_channels(s3_bucket: str, s3_prefix: str) -> dict:
    """Returns SageMaker data channel definitions pointing to S3."""
    return {
        "training": sagemaker.inputs.TrainingInput(
            s3_data=f"s3://{s3_bucket}/{s3_prefix}/train",
            content_type="application/x-image",
        ),
        "validation": sagemaker.inputs.TrainingInput(
            s3_data=f"s3://{s3_bucket}/{s3_prefix}/val",
            content_type="application/x-image",
        ),
    }


# ---------------------------------------------------------------------------
# Main launcher
# ---------------------------------------------------------------------------

def launch(args) -> str:
    """
    Submits the SageMaker training job and returns the S3 output path.
    """
    validate_config(args)

    session   = sagemaker.Session(boto_session=boto3.Session(region_name=args.region))
    job_name  = f"claimlens-yolov8-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    s3_output = f"s3://{args.s3_bucket}/claimlens/training-output"

    hyperparameters = {
        "model":         args.model,
        "epochs":        str(args.epochs),
        "batch":         str(args.batch),
        "imgsz":         str(args.imgsz),
        "optimizer":     args.optimizer,
        "lr0":           str(args.lr0),
        "lrf":           str(args.lrf),
        "warmup_epochs": str(args.warmup_epochs),
        "weight_decay":  str(args.weight_decay),
        "patience":      str(args.patience),
        "mosaic":        str(args.mosaic),
        "mixup":         str(args.mixup),
        "fliplr":        str(args.fliplr),
        "degrees":       str(args.degrees),
    }

    print(f"""
[launch] ── SageMaker Job Configuration ─────────────────────
  Job name      : {job_name}
  Instance      : {args.instance_type}  (~$0.74/hr for g4dn.xlarge)
  Region        : {args.region}
  IAM Role      : {args.role_arn}
  Data (S3)     : s3://{args.s3_bucket}/{args.s3_prefix}
  Output (S3)   : {s3_output}
  Model         : {args.model}
  Epochs        : {args.epochs}
  Batch         : {args.batch}
─────────────────────────────────────────────────────────────
""")

    # Entry point is our train_entry.py in the sagemaker/ folder
    entry_point_dir = str(Path(__file__).parent)

    estimator = PyTorch(
        entry_point="train_entry.py",
        source_dir=entry_point_dir,
        role=args.role_arn,
        instance_type=args.instance_type,
        instance_count=args.instance_count,
        volume_size=args.volume_size_gb,
        framework_version=PYTORCH_VERSION,
        py_version=PYTHON_VERSION,
        hyperparameters=hyperparameters,
        output_path=s3_output,
        base_job_name="claimlens-yolov8",
        sagemaker_session=session,

        # Install ultralytics inside the container
        # SageMaker PyTorch container already has torch, so we just add ultralytics
        environment={
            "PIP_PACKAGES": "ultralytics==8.2.18 Pillow==10.3.0"
        },

        # Keep logs streaming to terminal
        keep_alive_period_in_seconds=0,
    )

    print(f"[launch] Submitting job: {job_name}")
    print("[launch] Logs will stream here. This will take ~1 hour on g4dn.xlarge.\n")

    data_channels = get_data_channels(args.s3_bucket, args.s3_prefix)

    estimator.fit(
        inputs=data_channels,
        job_name=job_name,
        wait=True,       # stream logs to terminal and wait for completion
        logs="All",
    )

    model_s3_path = f"{s3_output}/{job_name}/output/model.tar.gz"

    print(f"""
[launch] ── Job Complete ────────────────────────────────────
  Model artifacts : {model_s3_path}
  best.pt is inside model.tar.gz at: model/best.pt

Next step:
  python sagemaker/export_from_s3.py --job-name {job_name} --bucket {args.s3_bucket}
─────────────────────────────────────────────────────────────
""")

    return model_s3_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Launch a YOLOv8 fine-tuning job on AWS SageMaker."
    )

    # AWS config
    parser.add_argument("--region",        default=DEFAULTS["region"])
    parser.add_argument("--role-arn",      default=DEFAULTS["role_arn"],
                        help="SageMaker IAM role ARN (or set SAGEMAKER_ROLE_ARN)")
    parser.add_argument("--s3-bucket",     default=DEFAULTS["s3_bucket"],
                        help="S3 bucket name (or set S3_BUCKET)")
    parser.add_argument("--s3-prefix",     default=DEFAULTS["s3_prefix"])
    parser.add_argument("--instance",      default=DEFAULTS["instance_type"],
                        dest="instance_type",
                        help="SageMaker instance type (default: ml.g4dn.xlarge ~$0.74/hr)")
    parser.add_argument("--instance-count",default=DEFAULTS["instance_count"], type=int)
    parser.add_argument("--volume-size",   default=DEFAULTS["volume_size_gb"],  type=int,
                        dest="volume_size_gb")

    # Hyperparameters
    parser.add_argument("--model",          default=DEFAULTS["model"])
    parser.add_argument("--epochs",         default=DEFAULTS["epochs"],         type=int)
    parser.add_argument("--batch",          default=DEFAULTS["batch"],          type=int)
    parser.add_argument("--imgsz",          default=DEFAULTS["imgsz"],          type=int)
    parser.add_argument("--optimizer",      default=DEFAULTS["optimizer"])
    parser.add_argument("--lr0",            default=DEFAULTS["lr0"],            type=float)
    parser.add_argument("--lrf",            default=DEFAULTS["lrf"],            type=float)
    parser.add_argument("--warmup-epochs",  default=DEFAULTS["warmup_epochs"],  type=float,
                        dest="warmup_epochs")
    parser.add_argument("--weight-decay",   default=DEFAULTS["weight_decay"],   type=float,
                        dest="weight_decay")
    parser.add_argument("--patience",       default=DEFAULTS["patience"],       type=int)
    parser.add_argument("--mosaic",         default=DEFAULTS["mosaic"],         type=float)
    parser.add_argument("--mixup",          default=DEFAULTS["mixup"],          type=float)
    parser.add_argument("--fliplr",         default=DEFAULTS["fliplr"],         type=float)
    parser.add_argument("--degrees",        default=DEFAULTS["degrees"],        type=float)

    args = parser.parse_args()
    launch(args)


if __name__ == "__main__":
    main()

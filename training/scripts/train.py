"""
YOLOv8 Fine-tuning Script
==========================
Fine-tunes a YOLOv8 model on the CarDD car damage dataset.

Model size options (trade-off: speed vs accuracy):
  yolov8n.pt  — nano,   ~3M params,  fastest, lowest accuracy
  yolov8s.pt  — small,  ~11M params, good balance  ← recommended start
  yolov8m.pt  — medium, ~25M params, better accuracy, needs more VRAM
  yolov8l.pt  — large,  ~43M params, high accuracy, needs GPU
  yolov8x.pt  — xlarge, ~68M params, best accuracy, needs strong GPU

Hardware guide:
  CPU only         → use yolov8n, epochs=30,  imgsz=416
  Mac MPS (M1/M2)  → use yolov8s, epochs=50,  imgsz=640  ← likely your case
  Single GPU       → use yolov8m, epochs=100, imgsz=640
  Multi-GPU        → use yolov8l, epochs=150, imgsz=800

Usage:
    # Default (auto-detects hardware)
    python scripts/train.py

    # Custom options
    python scripts/train.py --model yolov8m.pt --epochs 100 --batch 16

    # Resume interrupted training
    python scripts/train.py --resume runs/train/cardd_yolov8s/weights/last.pt
"""

import argparse
import os
import platform
import sys
from pathlib import Path

try:
    from ultralytics import YOLO
    import torch
except ImportError:
    print("Missing dependencies. Run:  pip install -r requirements.txt")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Hardware detection
# ---------------------------------------------------------------------------

def detect_device() -> str:
    """
    Returns the best available training device:
      'cuda'  — NVIDIA GPU
      'mps'   — Apple Silicon (M1/M2/M3)
      'cpu'   — fallback
    """
    if torch.cuda.is_available():
        device = "cuda"
        gpu = torch.cuda.get_device_name(0)
        print(f"[train] Device: CUDA — {gpu}")
    elif torch.backends.mps.is_available():
        device = "mps"
        print("[train] Device: Apple MPS (Metal Performance Shaders)")
    else:
        device = "cpu"
        print("[train] Device: CPU — training will be slow, use a smaller model")
    return device


def recommended_defaults(device: str) -> dict:
    """Returns sensible default hyperparameters based on device."""
    if device == "cuda":
        return {"model": "yolov8s.pt", "epochs": 100, "batch": 16, "imgsz": 640}
    elif device == "mps":
        return {"model": "yolov8s.pt", "epochs": 50,  "batch": 8,  "imgsz": 640}
    else:  # cpu
        return {"model": "yolov8n.pt", "epochs": 30,  "batch": 4,  "imgsz": 416}


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(args: argparse.Namespace) -> Path:
    """
    Runs YOLOv8 fine-tuning and returns the path to best.pt weights.
    """
    device  = args.device or detect_device()
    defaults = recommended_defaults(device)

    model_name = args.model   or defaults["model"]
    epochs     = args.epochs  or defaults["epochs"]
    batch      = args.batch   or defaults["batch"]
    imgsz      = args.imgsz   or defaults["imgsz"]

    data_yaml  = Path(args.data).resolve()
    runs_dir   = Path(args.runs).resolve()
    project    = str(runs_dir / "train")
    run_name   = args.name or f"cardd_{model_name.replace('.pt', '')}"

    print(f"""
[train] ── Configuration ──────────────────────────────────
  Model      : {model_name}
  Dataset    : {data_yaml}
  Epochs     : {epochs}
  Batch size : {batch}
  Image size : {imgsz}
  Device     : {device}
  Output     : {project}/{run_name}
────────────────────────────────────────────────────────────
""")

    if not data_yaml.exists():
        print(f"[train] ERROR: Dataset YAML not found: {data_yaml}")
        print("[train] Run prepare_dataset.py first.")
        sys.exit(1)

    # ── Load model ────────────────────────────────────────────────────────────
    if args.resume:
        # Resume from a checkpoint
        resume_path = Path(args.resume)
        if not resume_path.exists():
            print(f"[train] ERROR: Resume checkpoint not found: {resume_path}")
            sys.exit(1)
        print(f"[train] Resuming from: {resume_path}")
        model = YOLO(str(resume_path))
    else:
        # Start from pretrained COCO weights (transfer learning)
        print(f"[train] Loading pretrained weights: {model_name}")
        model = YOLO(model_name)

    # ── Fine-tune ─────────────────────────────────────────────────────────────
    results = model.train(
        data=str(data_yaml),
        epochs=epochs,
        batch=batch,
        imgsz=imgsz,
        device=device,
        project=project,
        name=run_name,
        resume=bool(args.resume),

        # ── Augmentation (helps with small dataset) ───────────────────────
        hsv_h=0.015,       # hue jitter — handles different lighting
        hsv_s=0.7,         # saturation jitter
        hsv_v=0.4,         # brightness jitter
        degrees=5.0,       # small rotation
        translate=0.1,     # translation
        scale=0.5,         # scale jitter
        flipud=0.0,        # no vertical flip (cars aren't upside down)
        fliplr=0.5,        # horizontal flip
        mosaic=1.0,        # mosaic augmentation — great for small objects
        mixup=0.1,         # MixUp augmentation

        # ── Training stability ────────────────────────────────────────────
        patience=20,       # early stopping — stop if no improvement for 20 epochs
        save=True,
        save_period=10,    # save checkpoint every 10 epochs
        val=True,          # validate after each epoch
        plots=True,        # save training plots (loss curves, confusion matrix)

        # ── Optimiser ─────────────────────────────────────────────────────
        optimizer="AdamW",
        lr0=0.001,         # initial learning rate
        lrf=0.01,          # final lr = lr0 * lrf
        warmup_epochs=3,   # linear LR warmup
        weight_decay=0.0005,

        # ── Logging ───────────────────────────────────────────────────────
        verbose=True,
    )

    # ── Results ───────────────────────────────────────────────────────────────
    best_weights = Path(project) / run_name / "weights" / "best.pt"

    print(f"""
[train] ── Training Complete ──────────────────────────────
  Best weights : {best_weights}
  mAP50        : {results.results_dict.get('metrics/mAP50(B)', 'N/A')}
  mAP50-95     : {results.results_dict.get('metrics/mAP50-95(B)', 'N/A')}

Next steps:
  Evaluate : python scripts/evaluate.py --weights {best_weights}
  Export   : python scripts/export_weights.py --weights {best_weights}
────────────────────────────────────────────────────────────
""")

    return best_weights


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Fine-tune YOLOv8 on the CarDD car damage dataset."
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="YOLOv8 model to start from (default: auto by device). "
             "Options: yolov8n.pt, yolov8s.pt, yolov8m.pt, yolov8l.pt, yolov8x.pt",
    )
    parser.add_argument(
        "--data", type=str,
        default=str(Path(__file__).parent.parent / "data" / "processed" / "dataset.yaml"),
        help="Path to dataset.yaml (default: data/processed/dataset.yaml)",
    )
    parser.add_argument(
        "--epochs", type=int, default=None,
        help="Number of training epochs (default: auto by device)",
    )
    parser.add_argument(
        "--batch", type=int, default=None,
        help="Batch size (default: auto by device)",
    )
    parser.add_argument(
        "--imgsz", type=int, default=None,
        help="Training image size in pixels (default: auto by device)",
    )
    parser.add_argument(
        "--device", type=str, default=None,
        choices=["cuda", "mps", "cpu"],
        help="Training device (default: auto-detect)",
    )
    parser.add_argument(
        "--runs", type=str,
        default=str(Path(__file__).parent.parent / "runs"),
        help="Directory to save training runs (default: runs/)",
    )
    parser.add_argument(
        "--name", type=str, default=None,
        help="Name for this training run (default: cardd_<model>)",
    )
    parser.add_argument(
        "--resume", type=str, default=None,
        help="Path to last.pt checkpoint to resume interrupted training",
    )

    args = parser.parse_args()
    train(args)


if __name__ == "__main__":
    main()

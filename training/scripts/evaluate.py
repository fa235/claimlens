"""
Model Evaluation Script
========================
Evaluates a fine-tuned YOLOv8 model on the CarDD test set and prints
a full metrics report including per-class AP scores.

Metrics reported:
  mAP50     — mean Average Precision at IoU=0.50  (primary metric)
  mAP50-95  — mean AP averaged over IoU 0.50–0.95 (stricter)
  Precision — of all predicted boxes, how many are correct
  Recall    — of all ground-truth boxes, how many were found
  Per-class AP — breakdown by damage type

Usage:
    python scripts/evaluate.py --weights runs/train/cardd_yolov8s/weights/best.pt
    python scripts/evaluate.py --weights best.pt --split test
    python scripts/evaluate.py --weights best.pt --visualise --num-images 20
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

try:
    from ultralytics import YOLO
    import torch
except ImportError:
    print("Missing dependencies. Run:  pip install -r requirements.txt")
    sys.exit(1)


CARDD_CLASSES = [
    "dent", "scratch", "crack", "glass shatter", "lamp broken", "tire flat"
]


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate(args: argparse.Namespace) -> dict:
    weights_path = Path(args.weights)
    if not weights_path.exists():
        print(f"[evaluate] ERROR: Weights not found: {weights_path}")
        sys.exit(1)

    data_yaml = Path(args.data).resolve()
    if not data_yaml.exists():
        print(f"[evaluate] ERROR: Dataset YAML not found: {data_yaml}")
        sys.exit(1)

    print(f"""
[evaluate] ── Configuration ────────────────────────────────
  Weights  : {weights_path}
  Dataset  : {data_yaml}
  Split    : {args.split}
  Device   : {args.device or 'auto'}
─────────────────────────────────────────────────────────────
""")

    model = YOLO(str(weights_path))

    # Run validation on the chosen split
    results = model.val(
        data=str(data_yaml),
        split=args.split,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device or ("cuda" if torch.cuda.is_available()
                               else "mps" if torch.backends.mps.is_available()
                               else "cpu"),
        plots=True,          # saves confusion matrix + PR curves
        save_json=True,      # saves COCO-format predictions
        verbose=True,
    )

    # ── Extract metrics ────────────────────────────────────────────────────
    rd = results.results_dict

    map50    = rd.get("metrics/mAP50(B)",    0.0)
    map5095  = rd.get("metrics/mAP50-95(B)", 0.0)
    precision = rd.get("metrics/precision(B)", 0.0)
    recall    = rd.get("metrics/recall(B)",    0.0)

    # Per-class AP (stored in results.ap_class_index and results.ap)
    per_class = {}
    if hasattr(results, "ap_class_index") and results.ap_class_index is not None:
        for idx, ap in zip(results.ap_class_index, results.ap):
            class_name = CARDD_CLASSES[idx] if idx < len(CARDD_CLASSES) else f"class_{idx}"
            per_class[class_name] = round(float(ap), 4)

    # ── Print report ───────────────────────────────────────────────────────
    print(f"""
[evaluate] ── Results ──────────────────────────────────────
  mAP50        : {map50:.4f}   (target: >0.50 is good, >0.65 is strong)
  mAP50-95     : {map5095:.4f}
  Precision    : {precision:.4f}
  Recall       : {recall:.4f}
""")

    if per_class:
        print("  Per-class AP@50:")
        for cls, ap in per_class.items():
            bar = "█" * int(ap * 20)
            print(f"    {cls:<20} {ap:.4f}  {bar}")

    print("─────────────────────────────────────────────────────────────")

    # ── Save JSON report ───────────────────────────────────────────────────
    report = {
        "timestamp":   datetime.utcnow().isoformat(),
        "weights":     str(weights_path),
        "split":       args.split,
        "mAP50":       round(map50, 4),
        "mAP50_95":    round(map5095, 4),
        "precision":   round(precision, 4),
        "recall":      round(recall, 4),
        "per_class_AP": per_class,
    }

    report_path = weights_path.parent.parent / "eval_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[evaluate] Report saved → {report_path}")

    # ── Visualise predictions ──────────────────────────────────────────────
    if args.visualise:
        visualise_predictions(model, data_yaml, args)

    return report


# ---------------------------------------------------------------------------
# Optional visualisation
# ---------------------------------------------------------------------------

def visualise_predictions(model, data_yaml: Path, args: argparse.Namespace):
    """Runs inference on a few test images and saves annotated outputs."""
    import glob, shutil
    from pathlib import Path

    test_img_dir = data_yaml.parent / "images" / args.split
    images = sorted(glob.glob(str(test_img_dir / "*.jpg")))[: args.num_images]

    if not images:
        print(f"[evaluate] No images found in {test_img_dir}")
        return

    out_dir = data_yaml.parent.parent / "runs" / "visualisations"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[evaluate] Saving {len(images)} prediction visualisations → {out_dir}")

    results = model.predict(
        source=images,
        imgsz=args.imgsz,
        conf=0.25,
        save=True,
        project=str(out_dir),
        name="predictions",
        exist_ok=True,
    )
    print(f"[evaluate] Visualisations saved to: {out_dir}/predictions/")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate a fine-tuned YOLOv8 model on CarDD."
    )
    parser.add_argument(
        "--weights", type=str, required=True,
        help="Path to fine-tuned weights (best.pt or last.pt)",
    )
    parser.add_argument(
        "--data", type=str,
        default=str(Path(__file__).parent.parent / "data" / "processed" / "dataset.yaml"),
        help="Path to dataset.yaml",
    )
    parser.add_argument(
        "--split", type=str, default="test",
        choices=["train", "val", "test"],
        help="Dataset split to evaluate on (default: test)",
    )
    parser.add_argument(
        "--imgsz", type=int, default=640,
        help="Inference image size (default: 640)",
    )
    parser.add_argument(
        "--batch", type=int, default=8,
        help="Batch size for evaluation (default: 8)",
    )
    parser.add_argument(
        "--device", type=str, default=None,
        choices=["cuda", "mps", "cpu"],
        help="Device (default: auto-detect)",
    )
    parser.add_argument(
        "--visualise", action="store_true",
        help="Save annotated prediction images from the test set",
    )
    parser.add_argument(
        "--num-images", type=int, default=20,
        help="Number of images to visualise (default: 20)",
    )

    args = parser.parse_args()
    evaluate(args)


if __name__ == "__main__":
    main()

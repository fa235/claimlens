"""
Export Weights to Backend
==========================
Copies the fine-tuned best.pt weights into the backend so the
FastAPI damage detection service picks them up automatically.

Also optionally exports to ONNX format for faster CPU inference.

Usage:
    # Copy best.pt to backend
    python scripts/export_weights.py --weights runs/train/cardd_yolov8s/weights/best.pt

    # Also export to ONNX
    python scripts/export_weights.py --weights best.pt --onnx
"""

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:
    from ultralytics import YOLO
except ImportError:
    print("Missing dependencies. Run:  pip install -r requirements.txt")
    sys.exit(1)


# Destination inside the backend
BACKEND_WEIGHTS_DIR = Path(__file__).parent.parent.parent / "backend" / "weights"
BACKEND_ENV_FILE    = Path(__file__).parent.parent.parent / "backend" / ".env"


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def copy_to_backend(weights_path: Path, dest_name: str = "damage_detector.pt") -> Path:
    """Copies .pt weights into backend/weights/ and returns the dest path."""
    BACKEND_WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKEND_WEIGHTS_DIR / dest_name
    shutil.copy2(weights_path, dest)
    print(f"[export] ✓ Copied weights → {dest}")
    return dest


def export_onnx(weights_path: Path) -> Path:
    """Exports the model to ONNX format for faster CPU inference."""
    print(f"[export] Exporting to ONNX…")
    model = YOLO(str(weights_path))
    onnx_path = model.export(format="onnx", dynamic=True, simplify=True)
    print(f"[export] ✓ ONNX exported → {onnx_path}")

    # Also copy ONNX to backend
    onnx_dest = BACKEND_WEIGHTS_DIR / "damage_detector.onnx"
    shutil.copy2(onnx_path, onnx_dest)
    print(f"[export] ✓ ONNX copied  → {onnx_dest}")
    return Path(onnx_path)


def update_env_file(weights_rel_path: str) -> None:
    """
    Updates YOLO_WEIGHTS in backend/.env to point to the new weights.
    If .env doesn't exist yet, creates it from .env.example.
    """
    env_example = BACKEND_ENV_FILE.parent / ".env.example"

    if not BACKEND_ENV_FILE.exists():
        if env_example.exists():
            shutil.copy2(env_example, BACKEND_ENV_FILE)
            print(f"[export] Created {BACKEND_ENV_FILE} from .env.example")
        else:
            BACKEND_ENV_FILE.write_text("")

    lines = BACKEND_ENV_FILE.read_text().splitlines()
    updated = False

    new_lines = []
    for line in lines:
        if line.startswith("YOLO_WEIGHTS="):
            new_lines.append(f"YOLO_WEIGHTS={weights_rel_path}")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"YOLO_WEIGHTS={weights_rel_path}")

    BACKEND_ENV_FILE.write_text("\n".join(new_lines) + "\n")
    print(f"[export] ✓ Updated YOLO_WEIGHTS in {BACKEND_ENV_FILE}")


def save_export_manifest(weights_path: Path, report: dict) -> None:
    """Saves a JSON manifest alongside the weights for traceability."""
    manifest_path = BACKEND_WEIGHTS_DIR / "manifest.json"
    manifest = {
        "exported_at":    datetime.utcnow().isoformat(),
        "source_weights": str(weights_path.resolve()),
        "model_file":     "damage_detector.pt",
        "classes": [
            "dent", "scratch", "crack",
            "glass shatter", "lamp broken", "tire flat"
        ],
        "eval_metrics": report,
    }
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"[export] ✓ Manifest saved → {manifest_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Export fine-tuned YOLOv8 weights to the backend."
    )
    parser.add_argument(
        "--weights", type=str, required=True,
        help="Path to fine-tuned best.pt weights",
    )
    parser.add_argument(
        "--name", type=str, default="damage_detector.pt",
        help="Destination filename in backend/weights/ (default: damage_detector.pt)",
    )
    parser.add_argument(
        "--onnx", action="store_true",
        help="Also export to ONNX format (faster CPU inference)",
    )
    parser.add_argument(
        "--no-env-update", action="store_true",
        help="Skip updating YOLO_WEIGHTS in backend/.env",
    )

    args = parser.parse_args()

    weights_path = Path(args.weights)
    if not weights_path.exists():
        print(f"[export] ERROR: Weights file not found: {weights_path}")
        sys.exit(1)

    print(f"\n[export] Source weights : {weights_path}")
    print(f"[export] Backend dir    : {BACKEND_WEIGHTS_DIR}\n")

    # Load eval report if it exists alongside the weights
    eval_report = {}
    report_path = weights_path.parent.parent / "eval_report.json"
    if report_path.exists():
        with open(report_path) as f:
            eval_report = json.load(f)
        print(f"[export] Found eval report: mAP50={eval_report.get('mAP50', 'N/A')}")

    # Copy .pt weights to backend
    dest = copy_to_backend(weights_path, dest_name=args.name)

    # Export ONNX if requested
    if args.onnx:
        export_onnx(weights_path)

    # Update backend .env
    if not args.no_env_update:
        rel_path = f"weights/{args.name}"
        update_env_file(rel_path)

    # Save manifest
    save_export_manifest(weights_path, eval_report)

    print(f"""
[export] ── Done ────────────────────────────────────────────
  Weights deployed to : {dest}
  Backend will use    : weights/{args.name}

  Restart the backend to load new weights:
    docker-compose restart backend
  or locally:
    uvicorn app.main:app --reload
─────────────────────────────────────────────────────────────
""")


if __name__ == "__main__":
    main()

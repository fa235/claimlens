"""
Dataset Preparation Script
===========================
Converts raw CarDD annotations (COCO format) into YOLOv8 format and
organises images + labels into data/processed/ ready for training.

CarDD annotation format (COCO-style per example):
  - "image"           : PIL image
  - "image_id"        : int
  - "width", "height" : int
  - "objects"         : {
        "id"          : list[int],
        "area"        : list[float],
        "bbox"        : list[[x, y, w, h]],   ← COCO absolute pixels
        "category_id" : list[int],             ← 0-indexed
        "segmentation": list[list[float]]      ← polygon coords
    }

YOLOv8 label format (one .txt per image):
  Each line: <class_id> <cx> <cy> <w> <h>
  All values normalised to [0, 1] by image width/height.

Usage:
    python scripts/prepare_dataset.py
    python scripts/prepare_dataset.py --raw data/raw --out data/processed
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

try:
    from PIL import Image
    from tqdm import tqdm
except ImportError:
    print("Missing dependencies. Run:  pip install -r requirements.txt")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CARDD_CLASSES = [
    "dent",           # 0
    "scratch",        # 1
    "crack",          # 2
    "glass shatter",  # 3
    "lamp broken",    # 4
    "tire flat",      # 5
]

# Map raw split folder names to processed split names
SPLIT_MAP = {
    "train":      "train",
    "validation": "val",
    "test":       "test",
}

MIN_BOX_AREA = 4  # pixels² — skip degenerate boxes smaller than this


# ---------------------------------------------------------------------------
# COCO bbox → YOLOv8 normalised xywh
# ---------------------------------------------------------------------------

def coco_to_yolo(bbox: list, img_w: int, img_h: int) -> tuple[float, float, float, float] | None:
    """
    Converts COCO [x_min, y_min, width, height] (absolute pixels)
    to YOLOv8 [cx, cy, w, h] (normalised 0-1).

    Returns None if the box is degenerate (zero area or out of bounds).
    """
    x_min, y_min, bw, bh = bbox

    if bw <= 0 or bh <= 0:
        return None
    if bw * bh < MIN_BOX_AREA:
        return None

    cx = (x_min + bw / 2) / img_w
    cy = (y_min + bh / 2) / img_h
    nw = bw / img_w
    nh = bh / img_h

    # Clamp to [0, 1]
    cx = max(0.0, min(1.0, cx))
    cy = max(0.0, min(1.0, cy))
    nw = max(0.0, min(1.0, nw))
    nh = max(0.0, min(1.0, nh))

    return cx, cy, nw, nh


# ---------------------------------------------------------------------------
# Single-example conversion
# ---------------------------------------------------------------------------

def convert_example(
    ann_path: Path,
    raw_img_path: Path,
    out_img_path: Path,
    out_lbl_path: Path,
) -> dict:
    """
    Converts one raw example (image + annotation JSON) to YOLOv8 format.

    Returns a stats dict: {"boxes": int, "skipped": int, "ok": bool}
    """
    stats = {"boxes": 0, "skipped": 0, "ok": False}

    # Load annotation
    with open(ann_path) as f:
        ann = json.load(f)

    img_w = ann.get("width")
    img_h = ann.get("height")
    objects = ann.get("objects", {})

    bboxes     = objects.get("bbox", [])
    cat_ids    = objects.get("category_id", [])

    if not bboxes or img_w is None or img_h is None:
        # No annotations — still copy image, write empty label file
        shutil.copy2(raw_img_path, out_img_path)
        out_lbl_path.write_text("")
        stats["ok"] = True
        return stats

    lines = []
    for bbox, cat_id in zip(bboxes, cat_ids):
        yolo_box = coco_to_yolo(bbox, img_w, img_h)
        if yolo_box is None:
            stats["skipped"] += 1
            continue
        cx, cy, nw, nh = yolo_box
        lines.append(f"{cat_id} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}")
        stats["boxes"] += 1

    # Copy image
    shutil.copy2(raw_img_path, out_img_path)

    # Write label file
    out_lbl_path.write_text("\n".join(lines))

    stats["ok"] = True
    return stats


# ---------------------------------------------------------------------------
# Split processing
# ---------------------------------------------------------------------------

def process_split(
    raw_dir: Path,
    out_dir: Path,
    raw_split: str,
    out_split: str,
) -> dict:
    """
    Processes all examples for one split.

    Returns aggregate stats.
    """
    ann_dir = raw_dir / raw_split / "annotations"
    img_dir = raw_dir / raw_split / "images"

    out_img_dir = out_dir / "images" / out_split
    out_lbl_dir = out_dir / "labels" / out_split
    out_img_dir.mkdir(parents=True, exist_ok=True)
    out_lbl_dir.mkdir(parents=True, exist_ok=True)

    ann_files = sorted(ann_dir.glob("*.json"))
    if not ann_files:
        print(f"  [prepare] WARNING: No annotation files found in {ann_dir}")
        return {"total": 0, "boxes": 0, "skipped_boxes": 0, "errors": 0}

    total_boxes   = 0
    skipped_boxes = 0
    errors        = 0

    for ann_path in tqdm(ann_files, desc=out_split, unit="img"):
        stem = ann_path.stem
        raw_img = img_dir / f"{stem}.jpg"

        if not raw_img.exists():
            errors += 1
            continue

        out_img = out_img_dir / f"{stem}.jpg"
        out_lbl = out_lbl_dir / f"{stem}.txt"

        try:
            stats = convert_example(ann_path, raw_img, out_img, out_lbl)
            total_boxes   += stats["boxes"]
            skipped_boxes += stats["skipped"]
            if not stats["ok"]:
                errors += 1
        except Exception as e:
            print(f"  [prepare] ERROR on {stem}: {e}")
            errors += 1

    return {
        "total":         len(ann_files),
        "boxes":         total_boxes,
        "skipped_boxes": skipped_boxes,
        "errors":        errors,
    }


# ---------------------------------------------------------------------------
# YAML config for YOLOv8
# ---------------------------------------------------------------------------

def write_yaml(out_dir: Path, classes: list[str]) -> Path:
    """Writes the dataset.yaml file that YOLOv8 reads during training."""
    yaml_path = out_dir / "dataset.yaml"

    class_lines = "\n".join(f"  - {c}" for c in classes)
    content = f"""# CarDD dataset — YOLOv8 format
# Auto-generated by prepare_dataset.py

path: {out_dir.resolve()}   # absolute path to dataset root
train: images/train
val:   images/val
test:  images/test

nc: {len(classes)}           # number of classes
names:
{class_lines}
"""
    yaml_path.write_text(content)
    print(f"[prepare] Dataset YAML written → {yaml_path}")
    return yaml_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert raw CarDD annotations to YOLOv8 format."
    )
    parser.add_argument(
        "--raw",
        type=str,
        default=str(Path(__file__).parent.parent / "data" / "raw"),
        help="Path to raw dataset (output of download_cardd.py)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=str(Path(__file__).parent.parent / "data" / "processed"),
        help="Output directory for processed YOLOv8 dataset",
    )
    args = parser.parse_args()

    raw_dir = Path(args.raw)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[prepare] Raw data:    {raw_dir}")
    print(f"[prepare] Output:      {out_dir}")
    print(f"[prepare] Classes:     {CARDD_CLASSES}\n")

    aggregate = {"total": 0, "boxes": 0, "skipped_boxes": 0, "errors": 0}

    for raw_split, out_split in SPLIT_MAP.items():
        split_dir = raw_dir / raw_split
        if not split_dir.exists():
            print(f"[prepare] Skipping '{raw_split}' — not found in {raw_dir}")
            continue

        print(f"[prepare] Processing split: {raw_split} → {out_split}")
        stats = process_split(raw_dir, out_dir, raw_split, out_split)

        for k in aggregate:
            aggregate[k] += stats[k]

        print(
            f"  ✓ {stats['total']} images | "
            f"{stats['boxes']} boxes | "
            f"{stats['skipped_boxes']} skipped | "
            f"{stats['errors']} errors"
        )

    # Write dataset YAML
    write_yaml(out_dir, CARDD_CLASSES)

    print(f"""
[prepare] Done.
  Total images : {aggregate['total']}
  Total boxes  : {aggregate['boxes']}
  Skipped boxes: {aggregate['skipped_boxes']}  (degenerate/tiny)
  Errors       : {aggregate['errors']}

Next step: python scripts/train.py
""")


if __name__ == "__main__":
    main()

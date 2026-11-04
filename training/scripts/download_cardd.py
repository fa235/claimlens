"""
CarDD Dataset Locator / Validator
=================================
The official CarDD dataset is NOT redistributable through an automated
download: access requires agreeing to the Flickr/Shutterstock license
terms on the official site. So this script does NOT fetch images.

Instead it:
  1. Points you to the official source
  2. Validates a locally-provided CarDD_COCO release
  3. Writes a manifest under training/data/raw/ so prepare_dataset.py can
     convert the COCO annotations into YOLOv8 format.

────────────────────────────────────────────────────────────────────────
WHY NOT Hugging Face?
    The `harpreetsahota/CarDD` HF dataset only exposes raw images
    (feature schema = {"image": Image}) with NO bounding boxes, so it
    cannot be used to train a detector. The official release ships COCO
    annotation JSONs with real boxes.
────────────────────────────────────────────────────────────────────────

Official source:
    https://cardd-ustc.github.io
    -> download CarDD_release.zip (Google Drive), unzip it. You'll get:

        CarDD_release/
          CarDD_COCO/
            annotations/
              instances_train2017.json
              instances_val2017.json
              instances_test2017.json
            train2017/   (*.jpg)
            val2017/     (*.jpg)
            test2017/    (*.jpg)

Usage:
    # Validate a local CarDD_COCO directory and stage it
    python scripts/download_cardd.py --coco-root /path/to/CarDD_COCO

    # Just validate, don't stage
    python scripts/download_cardd.py --coco-root /path/to/CarDD_COCO --check-only
"""

import argparse
import json
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OFFICIAL_URL = "https://cardd-ustc.github.io"

# COCO split folder name -> our split name
COCO_SPLITS = {
    "train2017": "train",
    "val2017":   "val",
    "test2017":  "test",
}

# Expected damage categories (order is informational only -- the real
# class mapping is derived from each JSON's "categories" array downstream).
EXPECTED_CATEGORIES = {
    "dent",
    "scratch",
    "crack",
    "glass shatter",
    "lamp broken",
    "tire flat",
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _annotation_path(coco_root: Path, coco_split: str) -> Path:
    return coco_root / "annotations" / f"instances_{coco_split}.json"


def validate_coco_root(coco_root: Path) -> dict:
    """
    Verifies the CarDD_COCO directory has the expected structure.

    Returns a dict describing which splits are present:
        {coco_split: {"images": int, "annotations": int, "categories": [..]}}
    Exits with a helpful message if the layout is clearly wrong.
    """
    if not coco_root.exists():
        print(f"[download] ERROR: --coco-root does not exist: {coco_root}")
        print(f"[download] Download the dataset from {OFFICIAL_URL} first.")
        sys.exit(1)

    ann_dir = coco_root / "annotations"
    if not ann_dir.exists():
        print(f"[download] ERROR: No 'annotations/' folder under {coco_root}.")
        print("[download] Did you point --coco-root at the CarDD_COCO directory?")
        print("[download] Expected layout:")
        print("    CarDD_COCO/annotations/instances_train2017.json")
        print("    CarDD_COCO/train2017/*.jpg")
        sys.exit(1)

    found = {}
    for coco_split in COCO_SPLITS:
        ann_path = _annotation_path(coco_root, coco_split)
        img_dir  = coco_root / coco_split

        if not ann_path.exists():
            # Not every release ships all three -- skip missing splits
            continue

        try:
            with open(ann_path) as f:
                coco = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[download] ERROR: Could not read {ann_path}: {e}")
            sys.exit(1)

        images      = coco.get("images", [])
        annotations = coco.get("annotations", [])
        categories  = [c.get("name", "") for c in coco.get("categories", [])]

        if not img_dir.exists():
            print(f"[download] WARNING: annotations present for '{coco_split}' "
                  f"but image folder missing: {img_dir}")

        found[coco_split] = {
            "images":      len(images),
            "annotations": len(annotations),
            "categories":  categories,
            "ann_path":    str(ann_path),
            "img_dir":     str(img_dir),
        }

    if not found:
        print(f"[download] ERROR: No instances_*2017.json files found in {ann_dir}.")
        print(f"[download] Expected at least instances_train2017.json")
        sys.exit(1)

    return found


def report(found: dict) -> None:
    print("\n[download] -- CarDD_COCO validation --------------------------------")
    for coco_split, info in found.items():
        our_split = COCO_SPLITS[coco_split]
        cats = info["categories"]
        cat_note = ""
        if cats:
            missing = EXPECTED_CATEGORIES - {c.lower() for c in cats}
            if missing:
                cat_note = f"  (!) categories differ from expected: {sorted(missing)} not found"
        print(f"  {coco_split:>10} -> {our_split:<5} | "
              f"{info['images']:>5} images | "
              f"{info['annotations']:>6} boxes | "
              f"classes={cats}{cat_note}")
    print("--------------------------------------------------------------------")


# ---------------------------------------------------------------------------
# Staging -- record where the COCO release lives so prepare_dataset finds it
# ---------------------------------------------------------------------------

def stage(coco_root: Path, raw_dir: Path, found: dict) -> None:
    """
    Writes a small manifest (data/raw/coco_source.json) that
    prepare_dataset.py reads to locate the COCO release. We do NOT copy
    images here -- prepare_dataset.py copies only the images it converts,
    avoiding a redundant full-dataset duplication on disk.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = raw_dir / "coco_source.json"

    manifest = {
        "coco_root": str(coco_root.resolve()),
        "splits": {
            COCO_SPLITS[cs]: {
                "annotations": info["ann_path"],
                "images_dir":  info["img_dir"],
                "num_images":  info["images"],
                "num_boxes":   info["annotations"],
            }
            for cs, info in found.items()
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"[download] OK: wrote manifest -> {manifest_path}")
    print(f"[download] Next step: python scripts/prepare_dataset.py")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Validate and stage the official CarDD_COCO release."
    )
    parser.add_argument(
        "--coco-root",
        type=str,
        default=os.environ.get("CARDD_COCO_ROOT", ""),
        help="Path to the unzipped CarDD_COCO directory "
             "(or set CARDD_COCO_ROOT). Download from " + OFFICIAL_URL,
    )
    parser.add_argument(
        "--raw",
        type=str,
        default=str(Path(__file__).parent.parent / "data" / "raw"),
        help="Where to write the staging manifest (default: data/raw)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only validate the release; do not write the staging manifest.",
    )
    args = parser.parse_args()

    if not args.coco_root:
        print(f"""
[download] ERROR: --coco-root is required.

The official CarDD dataset must be downloaded manually (license terms):

  1. Go to {OFFICIAL_URL}
  2. Download CarDD_release.zip and unzip it
  3. Re-run pointing at the CarDD_COCO folder:

     python scripts/download_cardd.py --coco-root /path/to/CarDD_COCO

  (or: export CARDD_COCO_ROOT=/path/to/CarDD_COCO)
""")
        sys.exit(1)

    coco_root = Path(args.coco_root).expanduser()
    found = validate_coco_root(coco_root)
    report(found)

    if args.check_only:
        print("[download] --check-only set; not staging.")
        return

    stage(coco_root, Path(args.raw), found)


if __name__ == "__main__":
    main()

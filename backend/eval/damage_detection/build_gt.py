"""Build ground-truth damage-category sets for a deterministic sample of
CarDD COCO val2017 images. Writes eval_cardd_gt.json."""
import json
import os
from collections import Counter

ANN_PATH = "/Users/apoorvakiran/Downloads/CarDD_release/CarDD_COCO/annotations/instances_val2017.json"
IMG_DIR = "/Users/apoorvakiran/Downloads/CarDD_release/CarDD_COCO/val2017"
N = 25
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(BACKEND_ROOT, "data", "eval_cardd_gt.json")


def main():
    d = json.load(open(ANN_PATH))
    cats = {c["id"]: c["name"] for c in d["categories"]}

    by_img = {}
    for a in d["annotations"]:
        by_img.setdefault(a["image_id"], set()).add(cats[a["category_id"]])

    rows = []
    for im in sorted(d["images"], key=lambda x: x["file_name"]):
        iid = im["id"]
        if iid not in by_img:
            continue
        fp = os.path.join(IMG_DIR, im["file_name"])
        if not os.path.exists(fp):
            continue
        rows.append({
            "image_id": iid,
            "file_name": im["file_name"],
            "path": fp,
            "gt_categories": sorted(by_img[iid]),
        })
        if len(rows) == N:
            break

    json.dump(rows, open(OUT, "w"), indent=2)
    print("categories:", list(cats.values()))
    print("num GT rows:", len(rows))
    cc = Counter(c for r in rows for c in r["gt_categories"])
    print("GT category frequency:", dict(cc))
    for r in rows[:5]:
        print(r["file_name"], r["gt_categories"])
    print("saved to", OUT)


if __name__ == "__main__":
    main()

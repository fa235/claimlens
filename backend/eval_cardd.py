"""
Evaluate ClaimLens damage detection against CarDD COCO val2017 ground truth.

For each image we run the real ClaimLens pipeline (analyze_image -> vision LLM),
collect the free-text damage types it reports, map them onto CarDD's 6 fixed
categories, and compare the predicted category set to the ground-truth set.

Metrics are computed as a multi-label problem over the 6 categories:
  - Per-category precision / recall / F1 (micro counts of TP/FP/FN).
  - Micro-averaged precision / recall / F1 across all categories.
  - Exact-set match rate (prediction set == GT set for the image).
  - "Any damage" detection accuracy (did we flag damage when damage exists).

Outputs:
  - eval_cardd_results.json  (machine-readable, full detail)
  - eval_cardd_report.md     (human-readable report)
"""
import asyncio
import json
import os
import sys

# Run against a throwaway sqlite DB so the import of app.* never touches postgres.
os.environ.setdefault("DATABASE_URL", "sqlite:///./eval_cardd.db")

sys.path.insert(0, os.path.dirname(__file__))

from app.services.analyzer import analyze_image  # noqa: E402
from app.core.config import settings  # noqa: E402

HERE = os.path.dirname(__file__)
GT_PATH = os.path.join(HERE, "eval_cardd_gt.json")
RESULTS_JSON = os.path.join(HERE, "eval_cardd_results.json")
REPORT_MD = os.path.join(HERE, "eval_cardd_report.md")

CATEGORIES = ["dent", "scratch", "crack", "glass shatter", "lamp broken", "tire flat"]

# Keyword -> CarDD category. Checked against the LLM's free-text "type" plus
# "location"/"description". Order matters: more specific first.
KEYWORD_MAP = [
    ("glass shatter", ["shatter", "windshield", "windscreen", "glass crack",
                        "broken glass", "cracked glass", "window crack",
                        "broken window", "cracked window"]),
    ("lamp broken",   ["headlight", "head light", "tail light", "taillight",
                        "head lamp", "tail lamp", "lamp", "light broken",
                        "broken light", "indicator", "turn signal", "fog light"]),
    ("tire flat",     ["flat tire", "flat tyre", "tire flat", "deflated",
                        "flat wheel", "punctured tire", "punctured tyre"]),
    ("crack",         ["crack", "cracked", "fracture", "split"]),
    ("dent",          ["dent", "dented", "ding", "crumple", "crushed",
                        "deformation", "deformed", "bent panel"]),
    ("scratch",       ["scratch", "scuff", "scrape", "abrasion", "paint damage",
                        "paint chip", "swirl", "mark"]),
]


def map_to_category(text: str):
    """Map one free-text damage phrase to a CarDD category (or None)."""
    t = (text or "").lower()
    for cat, keywords in KEYWORD_MAP:
        for kw in keywords:
            if kw in t:
                return cat
    return None


def predicted_categories(analysis: dict):
    """Collapse ClaimLens damages into a set of CarDD categories + record how."""
    preds = set()
    mapping_detail = []
    for d in analysis.get("damages", []) or []:
        phrase = " ".join(str(d.get(k, "")) for k in ("type", "location"))
        cat = map_to_category(phrase)
        mapping_detail.append({
            "raw_type": d.get("type"),
            "location": d.get("location"),
            "severity": d.get("severity"),
            "mapped_to": cat,
        })
        if cat:
            preds.add(cat)
    return preds, mapping_detail


async def run():
    gt_rows = json.load(open(GT_PATH))
    print(f"Provider: {settings.llm_provider} | vision model: {settings.openai_vision_model}")
    print(f"Evaluating {len(gt_rows)} images...\n")

    per_image = []
    # micro counts per category
    tp = {c: 0 for c in CATEGORIES}
    fp = {c: 0 for c in CATEGORIES}
    fn = {c: 0 for c in CATEGORIES}
    exact_matches = 0
    any_damage_correct = 0

    for i, row in enumerate(gt_rows, 1):
        path = row["path"]
        ext = os.path.splitext(path)[1].lower()
        media = "image/png" if ext == ".png" else "image/jpeg"
        with open(path, "rb") as f:
            image_bytes = f.read()

        try:
            analysis = await analyze_image(image_bytes, media)
            error = None
        except Exception as exc:  # keep going on single-image failure
            analysis = {"damages": []}
            error = f"{type(exc).__name__}: {exc}"

        gt = set(row["gt_categories"])
        preds, mapping_detail = predicted_categories(analysis)

        for c in CATEGORIES:
            if c in preds and c in gt:
                tp[c] += 1
            elif c in preds and c not in gt:
                fp[c] += 1
            elif c not in preds and c in gt:
                fn[c] += 1

        if preds == gt:
            exact_matches += 1
        # "any damage" detection: GT images all have damage, so correct = we found >=1
        if len(preds) >= 1 or analysis.get("vision_damage_detected"):
            any_damage_correct += 1

        per_image.append({
            "file_name": row["file_name"],
            "gt_categories": sorted(gt),
            "predicted_categories": sorted(preds),
            "exact_match": preds == gt,
            "raw_damages": mapping_detail,
            "repair_cost_estimate": analysis.get("repair_cost_estimate"),
            "damage_confidence": analysis.get("damage_confidence"),
            "error": error,
        })
        status = "OK " if error is None else "ERR"
        print(f"[{i:2}/{len(gt_rows)}] {status} {row['file_name']}  "
              f"GT={sorted(gt)}  PRED={sorted(preds)}  match={preds == gt}"
              + (f"  ({error})" if error else ""))

    # ── aggregate metrics ────────────────────────────────────────────────
    def prf(tp_, fp_, fn_):
        p = tp_ / (tp_ + fp_) if (tp_ + fp_) else 0.0
        r = tp_ / (tp_ + fn_) if (tp_ + fn_) else 0.0
        f = 2 * p * r / (p + r) if (p + r) else 0.0
        return p, r, f

    per_cat = {}
    for c in CATEGORIES:
        p, r, f = prf(tp[c], fp[c], fn[c])
        per_cat[c] = {"tp": tp[c], "fp": fp[c], "fn": fn[c],
                      "precision": p, "recall": r, "f1": f,
                      "support": tp[c] + fn[c]}

    TP, FP, FN = sum(tp.values()), sum(fp.values()), sum(fn.values())
    micro_p, micro_r, micro_f = prf(TP, FP, FN)
    n = len(gt_rows)

    summary = {
        "num_images": n,
        "provider": settings.llm_provider,
        "vision_model": settings.openai_vision_model,
        "micro": {"tp": TP, "fp": FP, "fn": FN,
                  "precision": micro_p, "recall": micro_r, "f1": micro_f},
        "exact_set_match_rate": exact_matches / n if n else 0.0,
        "any_damage_detection_rate": any_damage_correct / n if n else 0.0,
        "per_category": per_cat,
    }

    json.dump({"summary": summary, "per_image": per_image},
              open(RESULTS_JSON, "w"), indent=2)

    write_report(summary, per_image)
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(f"\nSaved: {RESULTS_JSON}\nSaved: {REPORT_MD}")


def write_report(summary, per_image):
    L = []
    L.append("# ClaimLens Evaluation on CarDD (COCO val2017)\n")
    L.append(f"- Images evaluated: **{summary['num_images']}**")
    L.append(f"- Provider / model: **{summary['provider']} / {summary['vision_model']}**")
    L.append(f"- Task: multi-label damage-category detection vs. CarDD ground truth")
    L.append(f"- Categories: {', '.join(CATEGORIES)}\n")

    m = summary["micro"]
    L.append("## Aggregate metrics\n")
    L.append("| Metric | Value |")
    L.append("|---|---|")
    L.append(f"| Micro precision | {m['precision']:.3f} |")
    L.append(f"| Micro recall | {m['recall']:.3f} |")
    L.append(f"| Micro F1 | {m['f1']:.3f} |")
    L.append(f"| Exact set-match rate | {summary['exact_set_match_rate']:.3f} |")
    L.append(f"| Any-damage detection rate | {summary['any_damage_detection_rate']:.3f} |")
    L.append(f"| TP / FP / FN | {m['tp']} / {m['fp']} / {m['fn']} |\n")

    L.append("## Per-category metrics\n")
    L.append("| Category | Support | TP | FP | FN | Precision | Recall | F1 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for c in CATEGORIES:
        pc = summary["per_category"][c]
        L.append(f"| {c} | {pc['support']} | {pc['tp']} | {pc['fp']} | {pc['fn']} | "
                 f"{pc['precision']:.3f} | {pc['recall']:.3f} | {pc['f1']:.3f} |")
    L.append("")

    L.append("## Per-image results\n")
    L.append("| Image | Ground truth | Predicted | Exact match |")
    L.append("|---|---|---|---|")
    for r in per_image:
        gt = ", ".join(r["gt_categories"]) or "—"
        pr = ", ".join(r["predicted_categories"]) or "—"
        mark = "yes" if r["exact_match"] else "no"
        note = " (error)" if r.get("error") else ""
        L.append(f"| {r['file_name']} | {gt} | {pr}{note} | {mark} |")
    L.append("")

    open(REPORT_MD, "w").write("\n".join(L))


if __name__ == "__main__":
    asyncio.run(run())

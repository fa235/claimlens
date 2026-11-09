"""
Compare a ClaimLens cost-estimator run against the Claude benchmark.

Treats Claude's per-item estimate as the reference value and measures how far
the evaluated ("candidate") model deviates. Reports:
  - Per-item: absolute error, signed error, pct error (vs Claude).
  - Aggregate: MAE, median AE, MAPE, mean signed bias, Pearson correlation.
  - Claim-total agreement: per-image total abs error + MAPE.
  - Per-damage-type breakdown (mean Claude, mean candidate, MAE).

NOTE: CarDD has no real cost labels. This measures candidate-vs-Claude
AGREEMENT, not accuracy against real repair prices.

  # score the GPT-4o run (default)
  python eval/cost_estimation/compare.py

  # score a GPT-OSS / Fireworks run
  python eval/cost_estimation/compare.py \
      --results reports/fireworks_cost_results.json \
      --out-json reports/cost_comparison_fireworks.json \
      --out-md   reports/cost_benchmark_report_fireworks.md
"""
import argparse
import json
import os
import statistics as st

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CLAUDE = os.path.join(BACKEND_ROOT, "data", "claude_cost_benchmark.json")
OPENAI = os.path.join(BACKEND_ROOT, "reports", "openai_cost_results.json")
OUT_JSON = os.path.join(BACKEND_ROOT, "reports", "cost_comparison.json")
OUT_MD = os.path.join(BACKEND_ROOT, "reports", "cost_benchmark_report.md")


def _resolve(path: str) -> str:
    """Accept paths relative to backend/ as well as absolute ones."""
    return path if os.path.isabs(path) else os.path.join(BACKEND_ROOT, path)


def _pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def main(results_path=OPENAI, out_json=OUT_JSON, out_md=OUT_MD, label=None):
    claude = {img["file_name"]: img["items"]
              for img in json.load(open(CLAUDE))["per_image"]}
    results_doc = json.load(open(results_path))
    candidate = {img["file_name"]: img["items"]
                 for img in results_doc["per_image"]}

    # run_openai.py records which model produced the file; fall back for older
    # result files that predate that field.
    if label is None:
        model = results_doc.get("model")
        provider = results_doc.get("provider")
        if provider and model:
            # "accounts/fireworks/models/gpt-oss-120b" -> "gpt-oss-120b"
            label = f"{provider} {model.rsplit('/', 1)[-1]}"
        else:
            label = "OpenAI gpt-4o"

    per_item = []
    claude_vals, cand_vals = [], []
    by_type = {}          # type -> {"claude": [...], "candidate": [...], "abs_err": [...]}
    claim_totals = []     # per-image (file, claude_total, candidate_total)

    for fname, c_items in claude.items():
        o_items = candidate.get(fname, [])
        o_by_idx = {it["index"]: it for it in o_items}
        c_total = o_total = 0

        for c in c_items:
            idx = c["index"]
            c_cost = c["cost"]
            o = o_by_idx.get(idx)
            o_cost = o["cost"] if o else None
            c_total += c_cost
            if o_cost is not None:
                o_total += o_cost

            if o_cost is None:
                continue

            abs_err = abs(o_cost - c_cost)
            signed = o_cost - c_cost
            pct = (signed / c_cost * 100.0) if c_cost else None

            per_item.append({
                "file_name": fname, "index": idx, "type": c["type"],
                "severity": c["severity"], "location": c["location"],
                "claude": c_cost, "candidate": o_cost,
                "abs_error": abs_err, "signed_error": signed,
                "pct_error": pct,
            })
            claude_vals.append(c_cost)
            cand_vals.append(o_cost)

            t = c["type"].lower()
            bt = by_type.setdefault(t, {"claude": [], "candidate": [], "abs_err": []})
            bt["claude"].append(c_cost)
            bt["candidate"].append(o_cost)
            bt["abs_err"].append(abs_err)

        claim_totals.append({
            "file_name": fname, "claude_total": c_total, "candidate_total": o_total,
            "abs_error": abs(o_total - c_total),
            "pct_error": ((o_total - c_total) / c_total * 100.0) if c_total else None,
        })

    # ── aggregate item-level metrics ──────────────────────────────────────
    abs_errs = [p["abs_error"] for p in per_item]
    signed_errs = [p["signed_error"] for p in per_item]
    pct_errs = [abs(p["pct_error"]) for p in per_item if p["pct_error"] is not None]

    agg = {
        "num_items": len(per_item),
        "mae": st.mean(abs_errs) if abs_errs else None,
        "median_ae": st.median(abs_errs) if abs_errs else None,
        "mape_pct": st.mean(pct_errs) if pct_errs else None,
        "median_ape_pct": st.median(pct_errs) if pct_errs else None,
        "mean_signed_bias": st.mean(signed_errs) if signed_errs else None,
        "pearson_r": _pearson(claude_vals, cand_vals),
        "mean_claude": st.mean(claude_vals) if claude_vals else None,
        "mean_candidate": st.mean(cand_vals) if cand_vals else None,
        "within_10pct": sum(1 for p in pct_errs if p <= 10) / len(pct_errs) if pct_errs else None,
        "within_25pct": sum(1 for p in pct_errs if p <= 25) / len(pct_errs) if pct_errs else None,
    }

    # ── claim-total metrics ───────────────────────────────────────────────
    ct_abs = [c["abs_error"] for c in claim_totals]
    ct_pct = [abs(c["pct_error"]) for c in claim_totals if c["pct_error"] is not None]
    claim_agg = {
        "num_claims": len(claim_totals),
        "total_mae": st.mean(ct_abs) if ct_abs else None,
        "total_mape_pct": st.mean(ct_pct) if ct_pct else None,
        "claude_grand_total": sum(c["claude_total"] for c in claim_totals),
        "candidate_grand_total": sum(c["candidate_total"] for c in claim_totals),
    }

    # ── per-type breakdown ────────────────────────────────────────────────
    type_rows = []
    for t, d in sorted(by_type.items(), key=lambda kv: -len(kv[1]["claude"])):
        type_rows.append({
            "type": t, "n": len(d["claude"]),
            "mean_claude": st.mean(d["claude"]),
            "mean_candidate": st.mean(d["candidate"]),
            "mae": st.mean(d["abs_err"]),
        })

    skipped = [f for f, items in candidate.items() if not items]
    out = {
        "note": f"Claude = benchmark/reference. {label} compared against it. "
                "Measures model agreement, NOT accuracy vs real prices.",
        "candidate_label": label,
        "candidate_results": os.path.relpath(results_path, BACKEND_ROOT),
        "images_with_no_candidate_items": skipped,
        "item_level": agg,
        "claim_total_level": claim_agg,
        "per_type": type_rows,
        "per_item": per_item,
        "claim_totals": claim_totals,
    }
    json.dump(out, open(out_json, "w"), indent=2)
    write_report(out, out_md)
    print(json.dumps({"item_level": agg, "claim_total_level": claim_agg}, indent=2))
    if skipped:
        print(f"\nWARNING: {len(skipped)} image(s) had no candidate items and were "
              f"skipped: {', '.join(skipped)}")
    print(f"\nEvaluated: {label}\nSaved: {out_json}\nSaved: {out_md}")


def write_report(out, out_md=OUT_MD):
    a = out["item_level"]
    c = out["claim_total_level"]
    label = out.get("candidate_label", "OpenAI gpt-4o")
    L = []
    L.append(f"# Cost Estimation Benchmark — {label} vs. Claude\n")
    L.append(f"**Benchmark model:** Claude (reference) · **Evaluated model:** {label}\n")
    L.append("Dataset: 25 CarDD images, 52 damage items. Both models received the "
             "**identical** damage type/severity/location inputs (vehicle fixed to Unknown).\n")
    L.append(f"> CarDD has no real repair-cost labels. This measures how closely the "
             f"{label} estimator **agrees with Claude**, not accuracy against real prices.\n")
    if out.get("images_with_no_candidate_items"):
        missing = out["images_with_no_candidate_items"]
        L.append(f"> **{len(missing)} image(s) produced no estimate** and are excluded: "
                 f"{', '.join(missing)}\n")

    L.append("## Item-level agreement (n = {})\n".format(a["num_items"]))
    L.append("| Metric | Value |")
    L.append("|---|---|")
    L.append(f"| Mean absolute error (MAE) | ${a['mae']:.0f} |")
    L.append(f"| Median absolute error | ${a['median_ae']:.0f} |")
    L.append(f"| MAPE (mean abs % error) | {a['mape_pct']:.1f}% |")
    L.append(f"| Median abs % error | {a['median_ape_pct']:.1f}% |")
    L.append(f"| Mean signed bias ({label} − Claude) | ${a['mean_signed_bias']:+.0f} |")
    L.append(f"| Pearson correlation r | {a['pearson_r']:.3f} |")
    L.append(f"| Mean cost — Claude / {label} | ${a['mean_claude']:.0f} / ${a['mean_candidate']:.0f} |")
    L.append(f"| Items within 10% of Claude | {a['within_10pct']*100:.0f}% |")
    L.append(f"| Items within 25% of Claude | {a['within_25pct']*100:.0f}% |\n")

    L.append("## Claim-total agreement (n = {} images)\n".format(c["num_claims"]))
    L.append("| Metric | Value |")
    L.append("|---|---|")
    L.append(f"| Mean abs error on claim total | ${c['total_mae']:.0f} |")
    L.append(f"| MAPE on claim total | {c['total_mape_pct']:.1f}% |")
    L.append(f"| Grand total — Claude | ${c['claude_grand_total']:,} |")
    L.append(f"| Grand total — {label} | ${c['candidate_grand_total']:,} |\n")

    L.append("## Per-damage-type breakdown\n")
    L.append(f"| Damage type | n | Mean Claude | Mean {label} | MAE |")
    L.append("|---|---|---|---|---|")
    for r in out["per_type"]:
        L.append(f"| {r['type']} | {r['n']} | ${r['mean_claude']:.0f} | "
                 f"${r['mean_candidate']:.0f} | ${r['mae']:.0f} |")
    L.append("")

    L.append("## Per-item detail\n")
    L.append(f"| Image | Item | Sev | Claude | {label} | Abs err | % err |")
    L.append("|---|---|---|---|---|---|---|")
    for p in out["per_item"]:
        pct = f"{p['pct_error']:+.0f}%" if p["pct_error"] is not None else "—"
        L.append(f"| {p['file_name']} | {p['type']} | {p['severity']} | "
                 f"${p['claude']} | ${p['candidate']} | ${p['abs_error']} | {pct} |")
    L.append("")

    open(out_md, "w").write("\n".join(L))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=OPENAI,
                        help="Cost-run JSON to score (default: reports/openai_cost_results.json)")
    parser.add_argument("--out-json", default=OUT_JSON)
    parser.add_argument("--out-md", default=OUT_MD)
    parser.add_argument("--label", default=None,
                        help="Name for the evaluated model in the report "
                             "(default: read from the results file)")
    args = parser.parse_args()
    main(_resolve(args.results), _resolve(args.out_json), _resolve(args.out_md), args.label)

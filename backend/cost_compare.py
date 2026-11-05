"""
Compare the OpenAI cost estimates against the Claude benchmark.

Treats Claude's per-item estimate as the reference value and measures how far
OpenAI's estimate deviates. Reports:
  - Per-item: absolute error, signed error, pct error (vs Claude).
  - Aggregate: MAE, median AE, MAPE, mean signed bias, Pearson correlation.
  - Claim-total agreement: per-image total abs error + MAPE.
  - Per-damage-type breakdown (mean Claude, mean OpenAI, MAE).

NOTE: CarDD has no real cost labels. This measures OpenAI-vs-Claude AGREEMENT,
not accuracy against real repair prices.

Writes cost_comparison.json and cost_benchmark_report.md.
"""
import json
import os
import statistics as st

HERE = os.path.dirname(__file__)
CLAUDE = os.path.join(HERE, "claude_cost_benchmark.json")
OPENAI = os.path.join(HERE, "openai_cost_results.json")
OUT_JSON = os.path.join(HERE, "cost_comparison.json")
OUT_MD = os.path.join(HERE, "cost_benchmark_report.md")


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


def main():
    claude = {img["file_name"]: img["items"]
              for img in json.load(open(CLAUDE))["per_image"]}
    openai = {img["file_name"]: img["items"]
              for img in json.load(open(OPENAI))["per_image"]}

    per_item = []
    claude_vals, openai_vals = [], []
    by_type = {}          # type -> {"claude": [...], "openai": [...], "abs_err": [...]}
    claim_totals = []     # per-image (file, claude_total, openai_total)

    for fname, c_items in claude.items():
        o_items = openai.get(fname, [])
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
                "claude": c_cost, "openai": o_cost,
                "abs_error": abs_err, "signed_error": signed,
                "pct_error": pct,
            })
            claude_vals.append(c_cost)
            openai_vals.append(o_cost)

            t = c["type"].lower()
            bt = by_type.setdefault(t, {"claude": [], "openai": [], "abs_err": []})
            bt["claude"].append(c_cost)
            bt["openai"].append(o_cost)
            bt["abs_err"].append(abs_err)

        claim_totals.append({
            "file_name": fname, "claude_total": c_total, "openai_total": o_total,
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
        "pearson_r": _pearson(claude_vals, openai_vals),
        "mean_claude": st.mean(claude_vals) if claude_vals else None,
        "mean_openai": st.mean(openai_vals) if openai_vals else None,
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
        "openai_grand_total": sum(c["openai_total"] for c in claim_totals),
    }

    # ── per-type breakdown ────────────────────────────────────────────────
    type_rows = []
    for t, d in sorted(by_type.items(), key=lambda kv: -len(kv[1]["claude"])):
        type_rows.append({
            "type": t, "n": len(d["claude"]),
            "mean_claude": st.mean(d["claude"]),
            "mean_openai": st.mean(d["openai"]),
            "mae": st.mean(d["abs_err"]),
        })

    out = {
        "note": "Claude = benchmark/reference. OpenAI compared against it. "
                "Measures model agreement, NOT accuracy vs real prices.",
        "item_level": agg,
        "claim_total_level": claim_agg,
        "per_type": type_rows,
        "per_item": per_item,
        "claim_totals": claim_totals,
    }
    json.dump(out, open(OUT_JSON, "w"), indent=2)
    write_report(out)
    print(json.dumps({"item_level": agg, "claim_total_level": claim_agg}, indent=2))
    print(f"\nSaved: {OUT_JSON}\nSaved: {OUT_MD}")


def write_report(out):
    a = out["item_level"]
    c = out["claim_total_level"]
    L = []
    L.append("# Cost Estimation Benchmark — OpenAI vs. Claude\n")
    L.append("**Benchmark model:** Claude (reference) · **Evaluated model:** OpenAI gpt-4o\n")
    L.append("Dataset: 25 CarDD images, 52 damage items. Both models received the "
             "**identical** damage type/severity/location inputs (vehicle fixed to Unknown).\n")
    L.append("> CarDD has no real repair-cost labels. This measures how closely the "
             "OpenAI estimator **agrees with Claude**, not accuracy against real prices.\n")

    L.append("## Item-level agreement (n = {})\n".format(a["num_items"]))
    L.append("| Metric | Value |")
    L.append("|---|---|")
    L.append(f"| Mean absolute error (MAE) | ${a['mae']:.0f} |")
    L.append(f"| Median absolute error | ${a['median_ae']:.0f} |")
    L.append(f"| MAPE (mean abs % error) | {a['mape_pct']:.1f}% |")
    L.append(f"| Median abs % error | {a['median_ape_pct']:.1f}% |")
    L.append(f"| Mean signed bias (OpenAI − Claude) | ${a['mean_signed_bias']:+.0f} |")
    L.append(f"| Pearson correlation r | {a['pearson_r']:.3f} |")
    L.append(f"| Mean cost — Claude / OpenAI | ${a['mean_claude']:.0f} / ${a['mean_openai']:.0f} |")
    L.append(f"| Items within 10% of Claude | {a['within_10pct']*100:.0f}% |")
    L.append(f"| Items within 25% of Claude | {a['within_25pct']*100:.0f}% |\n")

    L.append("## Claim-total agreement (n = {} images)\n".format(c["num_claims"]))
    L.append("| Metric | Value |")
    L.append("|---|---|")
    L.append(f"| Mean abs error on claim total | ${c['total_mae']:.0f} |")
    L.append(f"| MAPE on claim total | {c['total_mape_pct']:.1f}% |")
    L.append(f"| Grand total — Claude | ${c['claude_grand_total']:,} |")
    L.append(f"| Grand total — OpenAI | ${c['openai_grand_total']:,} |\n")

    L.append("## Per-damage-type breakdown\n")
    L.append("| Damage type | n | Mean Claude | Mean OpenAI | MAE |")
    L.append("|---|---|---|---|---|")
    for r in out["per_type"]:
        L.append(f"| {r['type']} | {r['n']} | ${r['mean_claude']:.0f} | "
                 f"${r['mean_openai']:.0f} | ${r['mae']:.0f} |")
    L.append("")

    L.append("## Per-item detail\n")
    L.append("| Image | Item | Sev | Claude | OpenAI | Abs err | % err |")
    L.append("|---|---|---|---|---|---|---|")
    for p in out["per_item"]:
        pct = f"{p['pct_error']:+.0f}%" if p["pct_error"] is not None else "—"
        L.append(f"| {p['file_name']} | {p['type']} | {p['severity']} | "
                 f"${p['claude']} | ${p['openai']} | ${p['abs_error']} | {pct} |")
    L.append("")

    open(OUT_MD, "w").write("\n".join(L))


if __name__ == "__main__":
    main()

"""
Build the per-image cost-estimation INPUTS from the saved vision run.

Source: eval_cardd_results.json (the 25-image vision evaluation). We reuse the
exact damage items the vision step produced so the Claude benchmark and the
OpenAI estimator score identical inputs — an apples-to-apples cost comparison.

The vision results did not persist car color/model, so we use a fixed
"Unknown" vehicle for every image. Both models receive the same vehicle string,
so this does not bias the comparison.

Writes cost_inputs.json:
[
  { "file_name": str,
    "car_color": "Unknown",
    "car_model": "Unknown",
    "damages": [ {type, severity, location}, ... ] },
  ...
]
"""
import json
import os

HERE = os.path.dirname(__file__)
SRC = os.path.join(HERE, "eval_cardd_results.json")
OUT = os.path.join(HERE, "cost_inputs.json")


def main():
    data = json.load(open(SRC))
    rows = []
    for img in data["per_image"]:
        damages = []
        for d in img.get("raw_damages", []) or []:
            dtype = (d.get("raw_type") or "").strip()
            if not dtype:
                continue
            damages.append({
                "type": dtype,
                "severity": (d.get("severity") or "medium").strip().lower(),
                "location": (d.get("location") or "unknown location").strip(),
            })
        rows.append({
            "file_name": img["file_name"],
            "car_color": "Unknown",
            "car_model": "Unknown",
            "damages": damages,
        })

    json.dump(rows, open(OUT, "w"), indent=2)
    n_items = sum(len(r["damages"]) for r in rows)
    print(f"images: {len(rows)}  total damage items: {n_items}")
    for r in rows:
        print(f"  {r['file_name']}: {[d['type'] + '/' + d['severity'] for d in r['damages']]}")
    print("saved to", OUT)


if __name__ == "__main__":
    main()

"""
Run the ClaimLens cost estimator (app.services.cost_estimator) on the same
damage items the Claude benchmark used.

Whichever provider the app is configured for is the one that gets exercised —
this script calls the production code path, it does not talk to any SDK itself.

  # GPT-4o (default)                 -> reports/openai_cost_results.json
  python eval/cost_estimation/run_openai.py

  # GPT-OSS on Fireworks            -> reports/fireworks_cost_results.json
  COST_LLM_PROVIDER=fireworks python eval/cost_estimation/run_openai.py

The output file is named after the provider so runs don't overwrite each other.
Pass --out to choose it explicitly.
"""
import argparse
import asyncio
import json
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./eval_cardd.db")
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, BACKEND_ROOT)

from app.services.cost_estimator import estimate_cost  # noqa: E402
from app.core.config import settings  # noqa: E402

INPUTS = os.path.join(BACKEND_ROOT, "data", "cost_inputs.json")

# Per-provider default output. "openai" keeps the original filename so the
# committed reports and compare.py defaults still line up.
_DEFAULT_OUT = {
    "openai": "openai_cost_results.json",
    "fireworks": "fireworks_cost_results.json",
    "bedrock": "bedrock_cost_results.json",
}


def _default_out(provider: str) -> str:
    name = _DEFAULT_OUT.get(provider, f"{provider}_cost_results.json")
    return os.path.join(BACKEND_ROOT, "reports", name)


async def run(out_path: str):
    rows = json.load(open(INPUTS))
    provider = settings.effective_cost_provider
    print(f"Provider: {provider} | cost model: {settings.cost_model_name}")
    print(f"Estimating costs for {len(rows)} images...\n")

    per_image = []
    for i, row in enumerate(rows, 1):
        try:
            result = await estimate_cost(
                car_color=row["car_color"],
                car_model=row["car_model"],
                damages=row["damages"],
            )
            items = [
                {"index": j, "type": it["type"], "severity": it["severity"],
                 "location": it["location"], "cost": it["cost"]}
                for j, it in enumerate(result.get("items", []))
            ]
            error = None
        except Exception as exc:
            items = []
            error = f"{type(exc).__name__}: {exc}"

        per_image.append({"file_name": row["file_name"], "items": items, "error": error})
        costs = [it["cost"] for it in items]
        print(f"[{i:2}/{len(rows)}] {row['file_name']}  costs={costs}"
              + (f"  ({error})" if error else ""))

    failed = sum(1 for p in per_image if p["error"])
    json.dump(
        {"provider": provider, "model": settings.cost_model_name, "per_image": per_image},
        open(out_path, "w"), indent=2,
    )
    if failed:
        print(f"\nWARNING: {failed}/{len(rows)} image(s) failed — see the "
              f'"error" fields. Those items are excluded from the comparison.')
    print("\nsaved to", out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None,
                        help="Output JSON path (default: named after the provider)")
    args = parser.parse_args()
    asyncio.run(run(args.out or _default_out(settings.effective_cost_provider)))

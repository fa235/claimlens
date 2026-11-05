"""
Run the ClaimLens OpenAI cost estimator (app.services.cost_estimator) on the
same damage items the Claude benchmark used. Writes openai_cost_results.json.
"""
import asyncio
import json
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./eval_cardd.db")
sys.path.insert(0, os.path.dirname(__file__))

from app.services.cost_estimator import estimate_cost  # noqa: E402
from app.core.config import settings  # noqa: E402

HERE = os.path.dirname(__file__)
INPUTS = os.path.join(HERE, "cost_inputs.json")
OUT = os.path.join(HERE, "openai_cost_results.json")


async def run():
    rows = json.load(open(INPUTS))
    print(f"Provider: {settings.llm_provider} | cost model: {settings.openai_cost_model}")
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

    json.dump({"per_image": per_image}, open(OUT, "w"), indent=2)
    print("\nsaved to", OUT)


if __name__ == "__main__":
    asyncio.run(run())

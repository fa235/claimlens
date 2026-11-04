"""
Cost estimation service — estimates a PER-ITEM repair cost for each detected
damage, using an LLM.

Provider selection (set LLM_PROVIDER in .env):
  bedrock  → Qwen3-32B via AWS Bedrock (needs on-demand quota)
  openai   → GPT-4o

Returns:
  {
    "items": [ {type, severity, location, cost: int}, ... ],  # one per input damage
    "total": int,          # sum of item costs (all items; declined handled upstream)
    "notes": str,          # brief overall explanation
  }

The LLM gives a single precise USD figure per damage item (not a range, not
text). The analyzer attaches these costs back onto the damage dicts and sums
them, excluding any items a processor later declines.
"""

import asyncio
import json
import re

from app.core.config import settings


# ── Prompt (same for both providers) ─────────────────────────────────────────

_SYSTEM_PROMPT = """
You are an automotive repair cost estimation expert with deep knowledge of
US repair shop pricing (parts + labor). You are given a vehicle and a numbered
list of individual damage items. Estimate a realistic repair cost for EACH item
separately.

Respond ONLY with valid JSON in this exact format:
{
  "items": [
    { "index": <0-based index matching the input list>, "cost": <integer USD, parts + labor for THIS item only> }
  ],
  "notes": "<one or two sentences on the main cost drivers>"
}
Rules:
- "cost" MUST be a single whole number in US dollars (e.g. 850). No ranges, no
  currency symbols, no text — just the integer.
- Provide exactly one entry per input damage item, matching its index.
- Base each cost on the item's type, severity, and location, plus the vehicle.
- Do not include any explanation or extra text outside the JSON.
""".strip()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_damages(damages: list) -> str:
    lines = []
    for i, d in enumerate(damages):
        lines.append(
            f"{i}. {d.get('type', 'damage')} "
            f"({d.get('severity', 'unknown')} severity) "
            f"at {d.get('location', 'unknown location')}"
        )
    return "\n".join(lines)


def _build_user_message(car_color: str, car_model: str, damages: list) -> str:
    return (
        f"Vehicle: {car_model} ({car_color})\n\n"
        f"Damage items:\n{_format_damages(damages)}\n\n"
        "Estimate a separate repair cost for each numbered item."
    )


def _coerce_cost(value) -> int:
    """Parse the model's per-item cost into a non-negative integer USD."""
    if isinstance(value, (int, float)):
        return max(0, int(round(value)))
    if isinstance(value, str):
        digits = re.sub(r"[^\d.]", "", value)
        try:
            return max(0, int(round(float(digits))))
        except (ValueError, TypeError):
            return 0
    return 0


def _parse_response(raw: str, damages: list) -> dict:
    """
    Strips markdown fences, parses JSON, and attaches a cost to each input
    damage by index. Missing/invalid entries default to 0.
    """
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {}

    # Map index -> cost from the model's response.
    cost_by_index = {}
    for entry in result.get("items", []) or []:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        if isinstance(idx, int):
            cost_by_index[idx] = _coerce_cost(entry.get("cost"))

    items = []
    total = 0
    for i, d in enumerate(damages):
        cost = cost_by_index.get(i, 0)
        items.append({
            "type": d.get("type", "damage"),
            "severity": d.get("severity", "medium"),
            "location": d.get("location", "unknown location"),
            "cost": cost,
        })
        total += cost

    notes = (result.get("notes") or "").strip() or "Per-item repair cost estimate."
    return {"items": items, "total": total, "notes": notes}


def _empty_result() -> dict:
    return {"items": [], "total": 0, "notes": "No damage detected."}


# ── Bedrock / Qwen3-32B ───────────────────────────────────────────────────────

async def _estimate_via_bedrock(car_color: str, car_model: str, damages: list) -> dict:
    from app.services.bedrock_client import get_bedrock_client

    if not settings.bedrock_cost_model_id:
        raise ValueError("BEDROCK_COST_MODEL_ID is not set.")

    client = get_bedrock_client()
    body = json.dumps({
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_message(car_color, car_model, damages)},
        ],
        "max_tokens": 500,
        "temperature": 0.2,
    })

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.invoke_model(
            modelId=settings.bedrock_cost_model_id,
            body=body,
            contentType="application/json",
            accept="application/json",
        ),
    )

    result_body = json.loads(response["body"].read().decode("utf-8"))
    raw = (
        result_body.get("choices", [{}])[0].get("message", {}).get("content", "")
        or result_body.get("outputs", [{}])[0].get("text", "")
        or result_body.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", "")
    )
    return _parse_response(raw, damages)


# ── OpenAI (GPT-4o) ───────────────────────────────────────────────────────────

async def _estimate_via_openai(car_color: str, car_model: str, damages: list) -> dict:
    from openai import AsyncOpenAI

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set.")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=settings.openai_cost_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_message(car_color, car_model, damages)},
        ],
        max_tokens=500,
        temperature=0.2,
    )
    raw = response.choices[0].message.content.strip()
    return _parse_response(raw, damages)


# ── Public interface ──────────────────────────────────────────────────────────

async def estimate_cost(car_color: str, car_model: str, damages: list) -> dict:
    """
    Estimates a precise per-item repair cost for each damage.

    Args:
        car_color:  Identified car color.
        car_model:  Identified car make/model/year.
        damages:    List of damage dicts [{type, severity, location}].

    Returns:
        {"items": [{type, severity, location, cost:int}], "total": int, "notes": str}
    """
    if not damages:
        return _empty_result()

    if settings.llm_provider == "bedrock":
        return await _estimate_via_bedrock(car_color, car_model, damages)
    return await _estimate_via_openai(car_color, car_model, damages)

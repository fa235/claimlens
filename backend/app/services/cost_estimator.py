"""
Cost estimation service — estimates a PER-ITEM repair cost for each detected
damage, using an LLM.

Provider selection (COST_LLM_PROVIDER in .env, falls back to LLM_PROVIDER):
  bedrock    → Qwen3-32B via AWS Bedrock (needs on-demand quota)
  openai     → GPT-4o
  fireworks  → GPT-OSS (or any open-weight text model) on Fireworks AI

Because this step is text-only, COST_LLM_PROVIDER can differ from the provider
used for the vision step — e.g. GPT-4o for vision, GPT-OSS on Fireworks here.

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
import logging
import re

from app.core.config import settings
from app.services.llm_json import extract_json_object, message_text

logger = logging.getLogger(__name__)


class CostEstimationError(RuntimeError):
    """The model replied, but no usable per-item costs could be read from it."""


# ── Prompt (same for all providers) ──────────────────────────────────────────

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
    Extracts the JSON estimate and attaches a cost to each input damage by
    index. Missing/invalid individual entries default to 0.

    Raises:
        CostEstimationError: if not a single per-item cost could be read, which
            means the reply was unusable. Returning all-zero costs here would
            surface a $0 claim that looks legitimate.
    """
    result = extract_json_object(raw, required_key="items")

    # Map index -> cost from the model's response.
    cost_by_index = {}
    for position, entry in enumerate(result.get("items", []) or []):
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        if isinstance(idx, bool):          # bool is an int subclass — reject it
            continue
        if not isinstance(idx, int):
            # Some open-weight models emit "index": "0", or omit it entirely.
            # Fall back to the entry's position in the list.
            try:
                idx = int(str(idx).strip())
            except (TypeError, ValueError):
                idx = position
        cost_by_index[idx] = _coerce_cost(entry.get("cost"))

    if damages and not cost_by_index:
        snippet = " ".join(raw.split())[:300] or "<empty response>"
        raise CostEstimationError(
            f"No per-item costs found in the model reply. Raw reply: {snippet}"
        )

    missing = [i for i in range(len(damages)) if i not in cost_by_index]
    if missing:
        logger.warning(
            "Cost estimator returned no cost for item index(es) %s; defaulting to $0.",
            missing,
        )

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


# ── OpenAI-compatible chat completions (OpenAI, Fireworks) ───────────────────

async def _estimate_via_openai_compatible(
    car_color: str,
    car_model: str,
    damages: list,
    *,
    api_key: str,
    model: str,
    base_url: str | None = None,
    max_tokens: int = 500,
    json_mode: bool = False,
    extra_body: dict | None = None,
) -> dict:
    """Single implementation for any provider speaking the OpenAI chat API."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_message(car_color, car_model, damages)},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if extra_body:
        kwargs["extra_body"] = extra_body

    response = await client.chat.completions.create(**kwargs)

    finish_reason = getattr(response.choices[0], "finish_reason", None)
    raw = message_text(response)
    if not raw:
        raise CostEstimationError(
            f"{model} returned an empty reply (finish_reason={finish_reason}). "
            "If this is a reasoning model, raise its max-tokens budget."
        )
    if finish_reason == "length":
        # The reply was cut off mid-JSON; parsing it would silently lose items.
        logger.warning(
            "%s hit the token limit (max_tokens=%s) — the estimate may be truncated.",
            model, max_tokens,
        )
    return _parse_response(raw, damages)


# ── OpenAI (GPT-4o) ───────────────────────────────────────────────────────────

async def _estimate_via_openai(car_color: str, car_model: str, damages: list) -> dict:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set.")

    return await _estimate_via_openai_compatible(
        car_color, car_model, damages,
        api_key=settings.openai_api_key,
        model=settings.openai_cost_model,
    )


# ── Fireworks AI (GPT-OSS) ────────────────────────────────────────────────────

async def _estimate_via_fireworks(car_color: str, car_model: str, damages: list) -> dict:
    """
    Calls an open-weight model (default: GPT-OSS 120B) on Fireworks AI.

    Fireworks serves an OpenAI-compatible endpoint, so this reuses the same
    client with a different base_url — no extra dependency. Two differences
    from the GPT-4o path matter:
      * GPT-OSS reasons before answering, so it needs a much larger token
        budget and accepts a `reasoning_effort` hint.
      * JSON mode constrains decoding to valid JSON, which an open-weight
        model needs more than GPT-4o does.
    """
    if not settings.fireworks_api_key:
        raise ValueError("FIREWORKS_API_KEY is not set.")

    extra_body = {}
    if settings.fireworks_reasoning_effort != "none":
        extra_body["reasoning_effort"] = settings.fireworks_reasoning_effort

    return await _estimate_via_openai_compatible(
        car_color, car_model, damages,
        api_key=settings.fireworks_api_key,
        base_url=settings.fireworks_base_url,
        model=settings.fireworks_cost_model,
        max_tokens=settings.fireworks_cost_max_tokens,
        json_mode=settings.fireworks_json_mode,
        extra_body=extra_body or None,
    )


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

    Raises:
        ValueError: provider unknown, or its credentials are missing.
        CostEstimationError: the model replied with nothing usable.
    """
    if not damages:
        return _empty_result()

    provider = settings.effective_cost_provider
    handlers = {
        "bedrock": _estimate_via_bedrock,
        "openai": _estimate_via_openai,
        "fireworks": _estimate_via_fireworks,
    }
    handler = handlers.get(provider)
    if handler is None:
        raise ValueError(
            f"Unknown cost provider {provider!r}. "
            f"Expected one of: {', '.join(sorted(handlers))}."
        )
    return await handler(car_color, car_model, damages)

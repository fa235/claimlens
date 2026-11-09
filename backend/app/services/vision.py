"""
Vision service — identifies car color, model, license plate, and visible
damage from an image using a single LLM vision call.

Provider selection (VISION_LLM_PROVIDER in .env, falls back to LLM_PROVIDER):
  bedrock    → Qwen-VL via AWS Bedrock (needs on-demand quota)
  openai     → GPT-4o Vision
  fireworks  → a multimodal model on Fireworks AI, default Qwen3.8-Flash-Next

The model MUST be vision-capable. Pointing this at a text-only model (e.g.
GPT-OSS, which the cost step can use) will not work.

This is the ONLY damage source in the pipeline — ClaimLens no longer runs a
separate object-detection model (cardamage / YOLO). The LLM both describes the
damage in prose AND returns a structured list the cost estimator consumes.

Returns:
  {
    "color": str,
    "model": str,
    "license_plate": str,          # "" if not visible/legible
    "damage_detected": bool,
    "damage_description": str,      # "" if no damage
    "damages": list[dict],         # [{type, severity, location}], [] if none
    "damage_confidence": float|None # 0..1 overall, None if no damage
  }
"""

import asyncio
import base64
import json
import logging

from app.core.config import settings
from app.services.llm_json import extract_json_object, message_text

logger = logging.getLogger(__name__)

# Fireworks caps total base64 image payload at 10MB per request.
_FIREWORKS_B64_LIMIT = 10 * 1024 * 1024


class VisionParseError(RuntimeError):
    """The vision model replied, but no appraisal could be read from it."""


# ── Prompt (same for both providers) ─────────────────────────────────────────

_SYSTEM_PROMPT = """
You are an automotive damage appraiser AI. Given a car image, identify:
1. The car color (e.g. "Midnight Blue", "Pearl White")
2. The car make, model, and approximate year (e.g. "2019 Toyota Camry")
3. The license/number plate text if one is visible and legible
4. All visible damage to the vehicle

Respond ONLY with valid JSON in this exact format:
{
  "color": "<color>",
  "model": "<make model year>",
  "license_plate": "<plate text, or empty string if not visible/legible>",
  "damage_detected": <true or false>,
  "damage_description": "<one-sentence summary of visible damage, or empty string if none>",
  "damages": [
    {
      "type": "<short damage type, e.g. dent, scratch, broken headlight, shattered glass, bumper damage, missing part>",
      "severity": "<low | medium | high>",
      "location": "<where on the car, e.g. front-left bumper, rear door, windshield>"
    }
  ],
  "damage_confidence": <number 0.0-1.0 — your overall confidence that the listed damage is correct>
}
Rules:
- If no plate is visible or readable, set "license_plate" to "".
- If you see no damage: set "damage_detected" to false, "damage_description" to "",
  "damages" to [], and "damage_confidence" to null.
- "severity" MUST be exactly one of: low, medium, high.
- List each distinct damaged area as a separate item in "damages".
- Do not include any explanation or extra text outside the JSON.
""".strip()

_VALID_SEVERITY = {"low", "medium", "high"}


# ── Response parser (shared) ──────────────────────────────────────────────────

def _coerce_damages(raw_damages) -> list:
    """Normalize the LLM's damages array into our strict schema."""
    if not isinstance(raw_damages, list):
        return []
    out = []
    for d in raw_damages:
        if not isinstance(d, dict):
            continue
        dtype = (d.get("type") or "").strip()
        if not dtype:
            continue
        severity = (d.get("severity") or "").strip().lower()
        if severity not in _VALID_SEVERITY:
            severity = "medium"
        location = (d.get("location") or "").strip() or "unknown location"
        out.append({"type": dtype, "severity": severity, "location": location})
    return out


def _parse_response(raw: str) -> dict:
    """
    Extracts the JSON appraisal from the model reply. Returns the "Unknown"
    fallback on failure.

    Tolerates markdown fences, <think> blocks, and prose around the payload,
    which open-weight and reasoning models on Fireworks routinely add.
    """
    result = extract_json_object(raw, required_key="damage_detected")
    if not result:
        # Do NOT fall through to the "Unknown / no damage" defaults here. That
        # produced a $0 claim marked "No damage detected" with no review flag —
        # indistinguishable from a genuine undamaged car. Observed with
        # reasoning VLMs that exhaust their token budget mid-thought.
        snippet = " ".join((raw or "").split())[:300] or "<empty response>"
        raise VisionParseError(
            f"Vision model returned no parseable JSON. Raw reply: {snippet}"
        )

    # Normalize license plate: treat null / whitespace as "not detected"
    plate = (result.get("license_plate") or "").strip()

    # Normalize damage flag: accept bool or common truthy strings
    raw_flag = result.get("damage_detected", False)
    if isinstance(raw_flag, str):
        damage_detected = raw_flag.strip().lower() in ("true", "yes", "1")
    else:
        damage_detected = bool(raw_flag)

    damage_description = (result.get("damage_description") or "").strip()
    damages = _coerce_damages(result.get("damages"))

    # Keep the three damage signals consistent with each other.
    if damages:
        damage_detected = True
    elif damage_detected and not damages:
        # Model said "damage" but gave no structured items — trust the flag,
        # synthesize a single item from the description so downstream still works.
        damages = [{
            "type": damage_description or "unspecified damage",
            "severity": "medium",
            "location": "unknown location",
        }]

    # Confidence: only meaningful when there is damage.
    conf = result.get("damage_confidence")
    try:
        conf = float(conf)
        conf = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        conf = None
    if not damages:
        conf = None

    return {
        "color": result.get("color", "Unknown"),
        "model": result.get("model", "Unknown"),
        "license_plate": plate,
        "damage_detected": damage_detected,
        "damage_description": damage_description,
        "damages": damages,
        "damage_confidence": conf,
    }


# ── Bedrock / Qwen-VL ─────────────────────────────────────────────────────────

async def _identify_via_bedrock(image_bytes: bytes, media_type: str) -> dict:
    """Calls a Qwen-VL model imported into AWS Bedrock (OpenAI-compatible body)."""
    from app.services.bedrock_client import get_bedrock_client

    if not settings.bedrock_vision_model_id:
        raise ValueError(
            "BEDROCK_VISION_MODEL_ID is not set. "
            "Import a vision model into Bedrock and paste the model ID in .env"
        )

    client = get_bedrock_client()
    b64    = base64.b64encode(image_bytes).decode("utf-8")

    body = json.dumps({
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:{media_type};base64,{b64}"}},
                    {"type": "text", "text": "Appraise this vehicle."},
                ],
            },
        ],
        "max_tokens": 500,
        "temperature": 0,
    })

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.invoke_model(
            modelId=settings.bedrock_vision_model_id,
            body=body,
            contentType="application/json",
            accept="application/json",
        ),
    )

    result_body = json.loads(response["body"].read().decode("utf-8"))
    raw = (
        result_body.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        or result_body.get("outputs", [{}])[0].get("text", "")
    )
    return _parse_response(raw)


# ── OpenAI-compatible vision (OpenAI, Fireworks) ──────────────────────────────

async def _identify_via_openai_compatible(
    image_bytes: bytes,
    media_type: str,
    *,
    api_key: str,
    model: str,
    base_url: str | None = None,
    max_tokens: int = 500,
    json_mode: bool = False,
    extra_body: dict | None = None,
) -> dict:
    """
    Single implementation for any provider speaking the OpenAI vision API.

    Fireworks accepts the identical `image_url` data-URL payload as OpenAI, so
    only the base URL, key, model and token budget differ.
    """
    from openai import AsyncOpenAI

    client   = AsyncOpenAI(api_key=api_key, base_url=base_url)
    b64      = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{media_type};base64,{b64}"

    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": "Appraise this vehicle."},
                ],
            },
        ],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if extra_body:
        kwargs["extra_body"] = extra_body

    response = await client.chat.completions.create(**kwargs)

    finish_reason = getattr(response.choices[0], "finish_reason", None)
    raw = message_text(response)
    if not raw:
        raise ValueError(
            f"{model} returned an empty reply (finish_reason={finish_reason}). "
            "If this is a reasoning model, raise its max-tokens budget."
        )
    if finish_reason == "length":
        logger.warning(
            "%s hit the token limit (max_tokens=%s) — the appraisal may be truncated.",
            model, max_tokens,
        )
    return _parse_response(raw)


# ── OpenAI (GPT-4o Vision) ────────────────────────────────────────────────────

async def _identify_via_openai(image_bytes: bytes, media_type: str) -> dict:
    """Calls GPT-4o Vision via the OpenAI chat.completions API."""
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set.")

    return await _identify_via_openai_compatible(
        image_bytes, media_type,
        api_key=settings.openai_api_key,
        model=settings.openai_vision_model,
    )


# ── Fireworks AI (Qwen3.8-Flash-Next and other VLMs) ──────────────────────────

async def _identify_via_fireworks(image_bytes: bytes, media_type: str) -> dict:
    """
    Calls a multimodal model on Fireworks AI — by default Qwen3.8-Flash-Next,
    an open-weight vision MoE, in place of GPT-4o.

    Fireworks' vision API mirrors OpenAI's, so this reuses the shared path.
    Two provider-specific details: a 10MB cap on the base64 payload, and the
    larger token budget a reasoning-capable model needs.
    """
    if not settings.fireworks_api_key:
        raise ValueError("FIREWORKS_API_KEY is not set.")

    # Base64 inflates by ~4/3. Check before spending a request on a 413.
    encoded_size = -(-len(image_bytes) // 3) * 4
    if encoded_size > _FIREWORKS_B64_LIMIT:
        raise ValueError(
            f"Image is too large for Fireworks: ~{encoded_size / 1e6:.1f}MB "
            f"base64-encoded, limit is {_FIREWORKS_B64_LIMIT / 1e6:.0f}MB. "
            "Downscale the image before uploading."
        )

    extra_body = {}
    if settings.fireworks_reasoning_effort != "none":
        extra_body["reasoning_effort"] = settings.fireworks_reasoning_effort

    return await _identify_via_openai_compatible(
        image_bytes, media_type,
        api_key=settings.fireworks_api_key,
        base_url=settings.fireworks_base_url,
        model=settings.fireworks_vision_model,
        max_tokens=settings.fireworks_vision_max_tokens,
        json_mode=settings.fireworks_json_mode,
        extra_body=extra_body or None,
    )


# ── Public interface ──────────────────────────────────────────────────────────

async def identify_vehicle(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    """
    Identifies the vehicle and all visible damage from image bytes.

    Routing by VISION_LLM_PROVIDER (falls back to LLM_PROVIDER):
      bedrock   → Qwen-VL on Bedrock
      openai    → GPT-4o Vision
      fireworks → Qwen3.8-Flash-Next (or another VLM) on Fireworks AI

    Args:
        image_bytes: Raw image file bytes.
        media_type:  MIME type of the image (e.g. "image/png"); defaults to JPEG.

    Returns:
        dict with color, model, license_plate, damage_detected,
        damage_description, damages (list), and damage_confidence.

    Raises:
        ValueError: provider unknown, credentials missing, or the model
            returned nothing usable.
    """
    provider = settings.effective_vision_provider
    handlers = {
        "bedrock": _identify_via_bedrock,
        "openai": _identify_via_openai,
        "fireworks": _identify_via_fireworks,
    }
    handler = handlers.get(provider)
    if handler is None:
        raise ValueError(
            f"Unknown vision provider {provider!r}. "
            f"Expected one of: {', '.join(sorted(handlers))}."
        )
    return await handler(image_bytes, media_type)

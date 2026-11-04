"""
Analyzer — orchestrates the analysis pipeline for a single image.

Pipeline (LLM-only):
  1. Vision LLM identifies the vehicle AND all visible damage (one call).
  2. Cost estimator turns vehicle + damage into a repair estimate.
  3. Flag low-confidence results for human review.

This is the single entry point the API route calls.
"""

from app.core.config import settings
from app.services.vision import identify_vehicle
from app.services.cost_estimator import estimate_cost


def _claim_total(damages: list) -> int:
    """Sum of per-item costs, EXCLUDING declined items."""
    total = 0
    for d in damages or []:
        if (d.get("status") or "").lower() == "declined":
            continue
        try:
            total += int(d.get("cost") or 0)
        except (TypeError, ValueError):
            continue
    return total


def _format_usd(amount: int) -> str:
    """Format an integer dollar amount, e.g. 1850 -> '$1,850'."""
    try:
        return f"${int(amount):,}"
    except (TypeError, ValueError):
        return "Unable to estimate"


async def analyze_image(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    """
    Runs the full analysis pipeline on image bytes.

    Args:
        image_bytes: Raw bytes of the uploaded image.
        media_type:  MIME type of the image (e.g. "image/png").

    Returns:
        {
          "color": str,
          "model": str,
          "license_plate": str,
          "vision_damage_detected": bool,
          "vision_damage_description": str,
          "damages": list,
          "damage_confidence": float | None,
          "repair_cost_estimate": str,
          "notes": str,
          "needs_human_review": bool,
          "review_reason": str | None,
        }
    """
    # Step 1: One vision call identifies the vehicle and all visible damage.
    vehicle_result = await identify_vehicle(image_bytes, media_type)

    color = vehicle_result["color"]
    model = vehicle_result["model"]
    license_plate = vehicle_result.get("license_plate", "")
    vision_damage_detected = vehicle_result.get("damage_detected", False)
    vision_damage_description = vehicle_result.get("damage_description", "")
    damages = vehicle_result.get("damages", [])
    damage_confidence = vehicle_result.get("damage_confidence")

    # Step 2: Estimate a precise repair cost for EACH damage item.
    cost_result = await estimate_cost(
        car_color=color,
        car_model=model,
        damages=damages,
    )

    # Attach per-item cost + line-item review fields onto each damage. Every
    # line starts "pending" (awaiting processor decision) and has no note.
    cost_items = cost_result.get("items", [])
    enriched_damages = []
    for i, d in enumerate(damages):
        cost = cost_items[i]["cost"] if i < len(cost_items) else 0
        enriched_damages.append({
            "type": d.get("type", "damage"),
            "severity": d.get("severity", "medium"),
            "location": d.get("location", "unknown location"),
            "cost": cost,
            "status": "pending",   # pending | approved | declined | modified | added
            "note": None,          # per-line processor note
        })

    # Total excludes declined items. At analysis time nothing is declined yet.
    total = _claim_total(enriched_damages)

    # Step 3: Flag for human review when the model isn't confident about the
    # damage it reported. With a single LLM source there's no second signal to
    # cross-check against, so low confidence is the trigger.
    needs_human_review = False
    review_reason = None
    if damages and damage_confidence is not None and damage_confidence < settings.review_confidence_threshold:
        needs_human_review = True
        review_reason = (
            f"Low damage confidence ({damage_confidence:.0%}, below "
            f"{settings.review_confidence_threshold:.0%}). Human review recommended."
        )

    return {
        "color": color,
        "model": model,
        "license_plate": license_plate,
        "vision_damage_detected": vision_damage_detected,
        "vision_damage_description": vision_damage_description,
        "damages": enriched_damages,
        "damage_confidence": damage_confidence,
        "repair_cost_total": total,
        "repair_cost_estimate": _format_usd(total),
        "notes": cost_result.get("notes", ""),
        "needs_human_review": needs_human_review,
        "review_reason": review_reason,
    }

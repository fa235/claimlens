"""
Fallback damage detector using the `cardamage` package.

NOTE: As of the LLM-only simplification, this module is NOT called by the
analysis pipeline. It is kept for potential future use (e.g. cross-checking
the LLM's damage read with a trained object detector). To re-enable it, import
`detect_damage_fallback` in analyzer.py and reinstate the cardamage/torch deps
in requirements.txt + Dockerfile.

Used when the primary YOLOv8 detector (primary_damage_detector.py) returns no
damage — which is expected until the YOLOv8 model is fine-tuned on CarDD.

`cardamage` ships a pretrained Mask R-CNN (R-101-DC5) from Hugging Face
(Naiscorp/car-damage-maskrcnn-r101-dc5):

    from cardamage import AutoModel
    model = AutoModel.from_pretrained("Naiscorp/car-damage-maskrcnn-r101-dc5")
    result = model.predict(pil_image)
    # result keys: boxes, scores, classes, labels, labels_en, masks, image_size

Returns the SAME shape as primary_damage_detector.detect_damage:
    {"damages": [{"type","severity","location","confidence"}], "damage_confidence": float|None}
"""

import asyncio
import io

from app.core.config import settings

# Lower threshold than the primary — this is a last-resort detector.
_FALLBACK_THRESHOLD = 0.25

_MODEL = None
_MODEL_ID = "Naiscorp/car-damage-maskrcnn-r101-dc5"

# Map the model's English labels to our short damage-type vocabulary.
_LABEL_MAP = {
    "Dent": "dent",
    "Paint scratch": "scratch",
    "Tear": "tear",
    "Missing part": "missing part",
    "Puncture": "puncture",
    "Broken lamp": "broken lamp",
    "Broken glass": "broken glass",
}


def _confidence_to_severity(conf: float) -> str:
    if conf >= 0.75:
        return "high"
    if conf >= 0.45:
        return "medium"
    return "low"


def _box_to_location(box, image_size) -> str:
    """Map a bounding-box center to a coarse region label (3x3 grid)."""
    x1, y1, x2, y2 = box
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2
    w, h = image_size
    col = "left" if cx < w / 3 else ("right" if cx > 2 * w / 3 else "center")
    row = "front" if cy < h / 3 else ("rear" if cy > 2 * h / 3 else "")
    if col == "center" and row:
        return row
    if col == "center":
        return "center body"
    return f"{row}-{col}" if row else f"{col} side"


def _load_model():
    """Loads the cardamage Mask R-CNN once and caches it."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    try:
        from cardamage import AutoModel
        _MODEL = AutoModel.from_pretrained(_MODEL_ID).eval()
        return _MODEL
    except Exception as e:
        print(f"[fallback_damage_detector] WARNING: could not load fallback model: {e}")
        return None


def _empty_result() -> dict:
    return {"damages": [], "damage_confidence": None}


def _run_inference(image_bytes: bytes) -> dict:
    from PIL import Image

    model = _load_model()
    if model is None:
        return _empty_result()

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    result = model.predict(image)

    boxes = result.get("boxes", [])
    scores = result.get("scores", [])
    labels_en = result.get("labels_en", [])
    image_size = result.get("image_size", image.size)

    boxes = boxes.tolist() if hasattr(boxes, "tolist") else list(boxes)
    scores = scores.tolist() if hasattr(scores, "tolist") else list(scores)

    damages = []
    max_conf = None
    for i, score in enumerate(scores):
        conf = float(score)
        if conf < _FALLBACK_THRESHOLD:
            continue
        label = labels_en[i] if i < len(labels_en) else ""
        dtype = _LABEL_MAP.get(label, (label or "damage").lower())
        location = _box_to_location(boxes[i], image_size) if i < len(boxes) else "unknown location"
        damages.append({
            "type": dtype,
            "severity": _confidence_to_severity(conf),
            "location": location,
            "confidence": round(conf, 2),
        })
        max_conf = conf if max_conf is None else max(max_conf, conf)

    return {"damages": damages, "damage_confidence": round(max_conf, 2) if max_conf else None}


async def detect_damage_fallback(image_bytes: bytes) -> dict:
    """
    Async wrapper around the cardamage Mask R-CNN detector.

    Returns {"damages": [...], "damage_confidence": float|None}.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_inference, image_bytes)

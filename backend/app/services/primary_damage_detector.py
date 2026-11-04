"""
Damage detection service — detects car damage regions in an image.

NOTE: As of the LLM-only simplification, this module is NOT called by the
analysis pipeline (the vision LLM now returns the damage list directly). It is
kept for potential future use. To re-enable it, import `detect_damage` in
analyzer.py and reinstate the ML deps (torch/cardamage/ultralytics) in
requirements.txt + Dockerfile.

Backend selection (set DAMAGE_DETECTOR in .env):
  huggingface → Naiscorp/car-damage-detection (pretrained, 7 damage classes)
                Used until our own YOLOv8 is trained on CarDD via SageMaker.
  yolo        → our fine-tuned YOLOv8 weights (set YOLO_WEIGHTS)

Returns:
    {"damages": [{"type","severity","location","confidence"}], "damage_confidence": float|None}
"""

import asyncio
import io

from PIL import Image

from app.core.config import settings


_HF_MODEL = None
_YOLO_MODEL = None

# Naiscorp/car-damage-detection class id → English name.
_HF_CLASS_NAMES = {
    0: "dent",
    1: "paint scratch",
    2: "tear",
    3: "missing part",
    4: "puncture",
    5: "broken lamp",
    6: "broken glass",
}

# Our own fine-tuned YOLOv8 class ids (CarDD-derived).
_YOLO_CLASSES = {
    0: "dent",
    1: "scratch",
    2: "crack",
    3: "glass shatter",
    4: "lamp broken",
    5: "tire flat",
}


def _confidence_to_severity(conf: float) -> str:
    if conf >= 0.75:
        return "high"
    if conf >= 0.45:
        return "medium"
    return "low"


def _estimate_location(box, image_size) -> str:
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


def _empty_result() -> dict:
    return {"damages": [], "damage_confidence": None}


# ── Hugging Face (cardamage) backend ─────────────────────────────────────────

def _load_hf_model():
    global _HF_MODEL
    if _HF_MODEL is not None:
        return _HF_MODEL
    try:
        import torch
        from cardamage import AutoModel
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _HF_MODEL = (
            AutoModel.from_pretrained(settings.hf_damage_model)
            .to(device)
            .eval()
        )
        print(f"[primary_damage_detector] Loaded HF model '{settings.hf_damage_model}' on {device}")
        return _HF_MODEL
    except Exception as e:
        print(f"[primary_damage_detector] WARNING: Could not load HF damage model: {e}")
        return None


def _detect_huggingface(image: Image.Image) -> dict:
    """Runs the Naiscorp cardamage model and maps output to our schema."""
    model = _load_hf_model()
    if model is None:
        return _empty_result()

    threshold = settings.damage_conf_threshold
    result = model.predict(image)

    # cardamage returns: boxes (N,4 xyxy), scores (N,), classes (N,), labels_en, masks
    boxes = result.get("boxes", [])
    scores = result.get("scores", [])
    classes = result.get("classes", [])
    labels_en = result.get("labels_en", [])
    image_size = result.get("image_size", image.size)

    boxes = boxes.tolist() if hasattr(boxes, "tolist") else list(boxes)
    scores = scores.tolist() if hasattr(scores, "tolist") else list(scores)
    classes = classes.tolist() if hasattr(classes, "tolist") else list(classes)

    damages = []
    max_conf = None
    for i, score in enumerate(scores):
        conf = float(score)
        if conf < threshold:
            continue
        if i < len(labels_en) and labels_en[i]:
            dtype = labels_en[i].lower()
        else:
            cls = int(classes[i]) if i < len(classes) else -1
            dtype = _HF_CLASS_NAMES.get(cls, "damage")
        location = _estimate_location(boxes[i], image_size) if i < len(boxes) else "unknown location"
        damages.append({
            "type": dtype,
            "severity": _confidence_to_severity(conf),
            "location": location,
            "confidence": round(conf, 2),
        })
        max_conf = conf if max_conf is None else max(max_conf, conf)

    return {"damages": damages, "damage_confidence": round(max_conf, 2) if max_conf else None}


# ── YOLOv8 backend ───────────────────────────────────────────────────────────

def _load_yolo_model():
    global _YOLO_MODEL
    if _YOLO_MODEL is not None:
        return _YOLO_MODEL
    try:
        from ultralytics import YOLO
        _YOLO_MODEL = YOLO(settings.yolo_weights)
        return _YOLO_MODEL
    except Exception as e:
        print(f"[primary_damage_detector] WARNING: Could not load YOLO model: {e}")
        return None


def _detect_yolo(image: Image.Image) -> dict:
    model = _load_yolo_model()
    if model is None:
        return _empty_result()

    threshold = settings.damage_conf_threshold
    results = model(image, verbose=False)

    damages = []
    max_conf = None
    for r in results:
        for b in r.boxes:
            conf = float(b.conf[0])
            if conf < threshold:
                continue
            cls = int(b.cls[0])
            dtype = _YOLO_CLASSES.get(cls, "damage")
            box = b.xyxy[0].tolist()
            location = _estimate_location(box, image.size)
            damages.append({
                "type": dtype,
                "severity": _confidence_to_severity(conf),
                "location": location,
                "confidence": round(conf, 2),
            })
            max_conf = conf if max_conf is None else max(max_conf, conf)

    return {"damages": damages, "damage_confidence": round(max_conf, 2) if max_conf else None}


# ── Public interface ──────────────────────────────────────────────────────────

async def detect_damage(image_bytes: bytes) -> dict:
    """
    Detects damage regions in an image.

    Returns {"damages": [...], "damage_confidence": float|None}.
    """
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as e:
        print(f"[primary_damage_detector] Invalid image: {e}")
        return _empty_result()

    loop = asyncio.get_event_loop()
    if settings.damage_detector == "yolo":
        return await loop.run_in_executor(None, _detect_yolo, image)
    return await loop.run_in_executor(None, _detect_huggingface, image)

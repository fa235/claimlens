"""
Annotation service — renders detected damage onto an image.

NOTE: As of the LLM-only simplification, this module is NOT called by the
analysis pipeline. It depends on the cardamage model (via
fallback_damage_detector) and is kept for potential future use alongside the
detector modules. To re-enable, import `annotate_damage` in analyzer.py,
reinstate SAVE_ANNOTATED handling, and restore the ML deps.

Produces a copy of the input image with bounding boxes, segmentation masks,
and English class labels drawn on top, using the `cardamage` model's built-in
visualization.

Public interface:
    annotated_bytes = await annotate_damage(image_bytes)   # -> bytes | None
"""

import asyncio
import io

_JPEG_QUALITY = 90


def _render(image_bytes: bytes) -> bytes | None:
    from PIL import Image

    # Reuse the fallback detector's cached cardamage model.
    from app.services.fallback_damage_detector import _load_model

    model = _load_model()
    if model is None:
        print("[annotator] model unavailable — skipping annotation")
        return None

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as e:
        print(f"[annotator] invalid image: {e}")
        return None

    # cardamage renders boxes + masks + labels. Default language is Vietnamese;
    # force English for ClaimLens.
    annotated = model.inference(
        image,
        draw_boxes=True,
        draw_labels=True,
        language="en",
    )

    buf = io.BytesIO()
    annotated.convert("RGB").save(buf, format="JPEG", quality=_JPEG_QUALITY)
    return buf.getvalue()


async def annotate_damage(image_bytes: bytes) -> bytes | None:
    """
    Async wrapper. Renders an annotated overlay for the given image.

    Returns JPEG bytes, or None if annotation could not be produced.
    """
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _render, image_bytes)
    except Exception as e:
        print(f"[annotator] annotation failed: {e}")
        return None

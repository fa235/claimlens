"""
API routes for ClaimLens.

POST  /api/analyze            — upload an image, get back analysis results
GET   /api/claims             — list claims (paginated, filter by status)
GET   /api/claims/{id}        — get a single claim by ID
PATCH /api/claims/{id}/review — save processor corrections to a claim
POST  /api/claims/{id}/approve— approve a claim
POST  /api/claims/{id}/reject — reject a claim
"""

from datetime import datetime, timezone
from typing import Optional, Literal

from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.claim import Claim
from app.services.analyzer import analyze_image
from app.services.storage import storage


# ── Request bodies ────────────────────────────────────────────────────────────

class CorrectionBody(BaseModel):
    """Processor's corrected values.

    `damages` is the full line-item list after review. Each item carries a
    per-line `status` (approved | declined | modified | added | pending) and an
    optional `note`. Any item that is modified, declined, or added MUST have a
    note. `final_note` is the processor's overall note on the claim.
    """
    color: Optional[str] = None
    model: Optional[str] = None
    damages: Optional[list] = None
    final_note: Optional[str] = None


class DecisionBody(BaseModel):
    """Approve/reject metadata."""
    processed_by: Optional[str] = None
    reason: Optional[str] = None

router = APIRouter(prefix="/api")

# Allowed image MIME types
_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
# Max upload size: 20 MB
_MAX_SIZE_BYTES = 20 * 1024 * 1024


# ── POST /api/analyze ─────────────────────────────────────────────────────────

@router.post("/analyze", summary="Analyze a car image")
async def analyze(
    file: UploadFile = File(..., description="Car image (JPEG, PNG, WEBP)"),
    db: Session = Depends(get_db),
):
    """
    Accepts a car photo, runs the full ML pipeline, persists the result,
    and returns structured analysis data.
    """
    # Validate content type
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{file.content_type}'. "
                   f"Accepted: JPEG, PNG, WEBP.",
        )

    # Read and size-check
    image_bytes = await file.read()
    if len(image_bytes) > _MAX_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="File too large. Maximum size is 20 MB.",
        )

    # Run ML pipeline
    try:
        result = await analyze_image(image_bytes)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"ML analysis failed: {exc}",
        )

    # Persist image to storage (local or S3)
    try:
        image_url = await storage.save(image_bytes, file.filename or "upload.jpg")
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Image storage failed: {exc}",
        )

    # Persist the annotated overlay if one was produced (best-effort — a
    # storage failure here must not fail the whole analysis).
    annotated_image_url = None
    annotated_bytes = result.get("annotated_image")
    if annotated_bytes:
        try:
            base = file.filename or "upload.jpg"
            annotated_name = f"annotated_{base.rsplit('.', 1)[0]}.jpg"
            annotated_image_url = await storage.save(annotated_bytes, annotated_name)
        except Exception as exc:
            # Log-and-continue: the claim is still valid without the overlay.
            print(f"[analyze] annotated image storage failed: {exc}")

    # Save claim to database
    claim = Claim(
        image_url=image_url,
        annotated_image_url=annotated_image_url,
        original_filename=file.filename,
        car_color=result["color"],
        car_model=result["model"],
        license_plate=result.get("license_plate"),
        vision_damage_detected=result.get("vision_damage_detected"),
        vision_damage_description=result.get("vision_damage_description"),
        damages=result["damages"],
        repair_cost_estimate=result["repair_cost_estimate"],
        notes=result["notes"],
        damage_confidence=result["damage_confidence"],
        needs_human_review=result.get("needs_human_review", False),
        review_reason=result.get("review_reason"),
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)

    return JSONResponse(content=claim.to_dict(), status_code=200)


# ── GET /api/claims ───────────────────────────────────────────────────────────

@router.get("/claims", summary="List claims (optionally filtered by status)")
def list_claims(
    status: Optional[Literal["pending", "approved", "rejected"]] = Query(
        None, description="Filter by claim status"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Results per page"),
    db: Session = Depends(get_db),
):
    """
    Returns a paginated list of claims, most recent first.
    Optionally filter by status (pending/approved/rejected).
    """
    query = db.query(Claim)
    if status:
        query = query.filter(Claim.status == status)

    total  = query.count()
    offset = (page - 1) * page_size
    claims = (
        query.order_by(Claim.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "status": status,
        "results": [c.to_dict() for c in claims],
    }


# ── GET /api/claims/{id} ──────────────────────────────────────────────────────

@router.get("/claims/{claim_id}", summary="Get a single claim")
def get_claim(claim_id: str, db: Session = Depends(get_db)):
    """
    Returns a single claim by its UUID.
    """
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found.")
    return claim.to_dict()


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_claim_or_404(claim_id: str, db: Session) -> Claim:
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found.")
    return claim


# ── PATCH /api/claims/{id}/review ─────────────────────────────────────────────

@router.patch("/claims/{claim_id}/review", summary="Save processor corrections")
def review_claim(
    claim_id: str,
    body: CorrectionBody,
    db: Session = Depends(get_db),
):
    """
    Applies a claim processor's corrections to the ML predictions.

    Updates the live claim fields AND records the corrections in
    corrected_data for future model retraining.
    """
    claim = _get_claim_or_404(claim_id, db)

    # Capture the original ML prediction before overwriting (for training data)
    corrections = claim.corrected_data or {}
    corrections["original"] = {
        "color": claim.car_color,
        "model": claim.car_model,
        "damages": claim.damages,
        "repair_cost_estimate": claim.repair_cost_estimate,
    }
    changed = {}

    if body.color is not None and body.color != claim.car_color:
        claim.car_color = body.color
        changed["color"] = body.color
    if body.model is not None and body.model != claim.car_model:
        claim.car_model = body.model
        changed["model"] = body.model

    # ── Per-item damage review ────────────────────────────────────────────
    # Each line's status drives whether a note is required and whether it
    # counts toward the total. modified/declined/added MUST have a note.
    if body.damages is not None:
        cleaned = []
        for item in body.damages:
            if not isinstance(item, dict):
                continue
            status = (item.get("status") or "pending").lower()
            note = (item.get("note") or "").strip()

            if status in ("modified", "declined", "added") and not note:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"A note is required for every {status} damage item. "
                        f"Please explain the change to "
                        f"'{item.get('type', 'this item')}'."
                    ),
                )

            try:
                cost = int(item.get("cost") or 0)
            except (TypeError, ValueError):
                cost = 0

            cleaned.append({
                "type": (item.get("type") or "damage").strip() or "damage",
                "severity": (item.get("severity") or "medium").strip().lower(),
                "location": (item.get("location") or "unknown location").strip(),
                "cost": max(0, cost),
                "status": status,
                "note": note or None,
            })

        claim.damages = cleaned
        changed["damages"] = cleaned

        # Recompute the total, EXCLUDING declined items.
        total = sum(d["cost"] for d in cleaned if d["status"] != "declined")
        claim.repair_cost_estimate = f"${total:,}"
        changed["repair_cost_estimate"] = claim.repair_cost_estimate

    # ── Final claim-level note ────────────────────────────────────────────
    final_note = (body.final_note or "").strip()
    if final_note:
        corrections["final_note"] = final_note
        claim.notes = (
            f"{claim.notes}\n\n[Processor note] {final_note}"
            if claim.notes else f"[Processor note] {final_note}"
        )

    corrections["corrected"] = changed
    claim.corrected_data = corrections
    # reviewed=True if nothing was changed (prediction accepted as-is)
    claim.reviewed = len(changed) == 0

    db.commit()
    db.refresh(claim)
    return claim.to_dict()


# ── POST /api/claims/{id}/approve ─────────────────────────────────────────────

@router.post("/claims/{claim_id}/approve", summary="Approve a claim")
def approve_claim(
    claim_id: str,
    body: DecisionBody,
    db: Session = Depends(get_db),
):
    """Marks a claim as approved."""
    claim = _get_claim_or_404(claim_id, db)

    claim.status          = "approved"
    claim.processed_by    = body.processed_by
    claim.decision_reason = body.reason
    claim.processed_at    = datetime.now(timezone.utc)

    db.commit()
    db.refresh(claim)
    return claim.to_dict()


# ── POST /api/claims/{id}/reject ──────────────────────────────────────────────

@router.post("/claims/{claim_id}/reject", summary="Reject a claim")
def reject_claim(
    claim_id: str,
    body: DecisionBody,
    db: Session = Depends(get_db),
):
    """Marks a claim as rejected. A reason is recommended."""
    claim = _get_claim_or_404(claim_id, db)

    claim.status          = "rejected"
    claim.processed_by    = body.processed_by
    claim.decision_reason = body.reason
    claim.processed_at    = datetime.now(timezone.utc)

    db.commit()
    db.refresh(claim)
    return claim.to_dict()

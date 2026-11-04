"""
Claim ORM model — stores every analysis result with the image reference.

Table: claims
Each row = one uploaded image + full ML analysis result.
Also used as training data for future fine-tuning.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Float, DateTime, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base


class Claim(Base):
    __tablename__ = "claims"

    # ── Primary key ───────────────────────────────────────────
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # ── Image reference ───────────────────────────────────────
    # URL from storage service (local path or S3 HTTPS URL)
    image_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=True)

    # Annotated overlay (boxes + masks + labels) when SAVE_ANNOTATED is enabled.
    # None when annotation is disabled or could not be produced.
    annotated_image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # ── ML results ────────────────────────────────────────────
    car_color: Mapped[str | None] = mapped_column(String(100), nullable=True)
    car_model: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # License/number plate read by the vision model ("" if not legible)
    license_plate: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Vision model's own damage read (independent of the object detector below)
    vision_damage_detected: Mapped[bool | None] = mapped_column(nullable=True)
    vision_damage_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # List of damage items: [{"type": "dent", "severity": "high", "location": "front bumper"}]
    damages: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Human-readable cost estimate e.g. "$1,200 – $1,800"
    repair_cost_estimate: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Additional LLM notes / reasoning
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Raw confidence score from YOLO (0.0 – 1.0)
    damage_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Human-in-the-loop ─────────────────────────────────────
    # Set True when the vision and detector damage signals disagree, meaning
    # the automated result can't be trusted and a human must review it.
    needs_human_review: Mapped[bool] = mapped_column(default=False, nullable=False)
    # Why review was triggered (None when needs_human_review is False)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Claim processing workflow ─────────────────────────────
    # "pending"  = awaiting processor review (default on upload)
    # "approved" = processor approved the claim
    # "rejected" = processor rejected the claim
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)

    # Who processed it + optional reason (e.g. rejection reason)
    processed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Fine-tuning feedback ──────────────────────────────────
    # Human-corrected values stored here for future training runs
    # None = not yet reviewed, True = approved, False = corrected
    reviewed: Mapped[bool | None] = mapped_column(nullable=True, default=None)
    corrected_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # ── Timestamps ────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "image_url": self.image_url,
            "annotated_image_url": self.annotated_image_url,
            "color": self.car_color,
            "model": self.car_model,
            "license_plate": self.license_plate,
            "vision_damage_detected": self.vision_damage_detected,
            "vision_damage_description": self.vision_damage_description,
            "damages": self.damages or [],
            "repair_cost_estimate": self.repair_cost_estimate,
            "notes": self.notes,
            "damage_confidence": self.damage_confidence,
            "needs_human_review": self.needs_human_review,
            "review_reason": self.review_reason,
            "status": self.status,
            "processed_by": self.processed_by,
            "decision_reason": self.decision_reason,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "reviewed": self.reviewed,
            "corrected_data": self.corrected_data,
            "created_at": self.created_at.isoformat(),
        }

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    """
    All configuration is read from environment variables.
    Defaults are safe for local development.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── App ───────────────────────────────────────────────────
    app_name: str = "ClaimLens API"
    debug: bool = False

    # ── LLM provider ─────────────────────────────────────────
    # "bedrock" — Qwen via AWS Bedrock (needs on-demand quota)
    # "openai"  — GPT-4o for both vision and text
    llm_provider: Literal["bedrock", "openai"] = "bedrock"

    # ── AWS Bedrock — Qwen models ────────────────────────────
    # Both are native Bedrock models — no import needed.
    # Vision : Qwen3-VL-235B  (multimodal, image + text)
    # Text   : Qwen3-32B      (cost estimation)
    bedrock_vision_model_id: str = "qwen.qwen3-vl-235b-a22b"
    bedrock_cost_model_id: str   = "qwen.qwen3-32b-v1:0"
    aws_region: str = "us-east-1"

    # ── OpenAI fallback ───────────────────────────────────────
    # Only required when llm_provider=openai
    openai_api_key: str = ""
    openai_vision_model: str = "gpt-4o"
    openai_cost_model: str = "gpt-4o"

    # ── AWS credentials (shared by Bedrock + S3) ──────────────
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # ── Storage ───────────────────────────────────────────────
    # "local" stores files in uploads/ folder
    # "s3"    stores files in AWS S3
    storage_backend: Literal["local", "s3"] = "local"
    upload_dir: str = "uploads"

    # S3 (required when storage_backend=s3)
    s3_bucket: str = ""

    # ── Database ──────────────────────────────────────────────
    database_url: str = "postgresql://claimlens:claimlens@localhost:5432/claimlens"

    # ── Damage detection ──────────────────────────────────────
    # "huggingface" — Naiscorp/car-damage-detection (pretrained, 7 classes)
    #                 Use this until our own YOLOv8 is trained on SageMaker.
    # "yolo"         — our fine-tuned YOLOv8 weights (set YOLO_WEIGHTS)
    damage_detector: Literal["huggingface", "yolo"] = "huggingface"

    # Hugging Face model repo id for the pretrained damage detector
    hf_damage_model: str = "Naiscorp/car-damage-detection"

    # Minimum confidence to keep a detection (HF model note: dents can score ~0.5)
    damage_conf_threshold: float = 0.5

    # When True, each analyzed image also gets an annotated overlay (boxes +
    # masks + labels) rendered and persisted via the storage backend.
    # Only supported with the cardamage model (DAMAGE_DETECTOR=huggingface).
    # NOTE: dormant in the current LLM-only pipeline.
    save_annotated: bool = False

    # Damage-confidence below this fraction flags a claim for human review
    # (LLM-only pipeline — the vision model returns an overall confidence).
    review_confidence_threshold: float = 0.6

    # ── YOLOv8 ───────────────────────────────────────────────
    # Path to fine-tuned weights; falls back to pretrained yolov8n.pt if not set
    yolo_weights: str = "yolov8n.pt"

    # ── CORS ──────────────────────────────────────────────────
    # Comma-separated list of allowed frontend origins.
    # Defaults cover local dev; add the deployed frontend URL in production.
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


# Singleton — import this everywhere
settings = Settings()

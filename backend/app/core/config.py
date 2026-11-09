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
    # Applies to BOTH the vision step and the cost step.
    # "bedrock" — Qwen via AWS Bedrock (needs on-demand quota)
    # "openai"  — GPT-4o for both vision and text
    llm_provider: Literal["bedrock", "openai"] = "bedrock"

    # ── Vision-step provider override ────────────────────────
    # "auto"      — follow llm_provider (default, previous behaviour)
    # "bedrock"   — Qwen-VL on Bedrock
    # "openai"    — openai_vision_model (GPT-4o)
    # "fireworks" — a multimodal model on Fireworks AI, e.g. Qwen3.8-Flash-Next
    # The model MUST be vision-capable; a text-only model (GPT-OSS) will fail
    # or hallucinate here.
    vision_llm_provider: Literal["auto", "bedrock", "openai", "fireworks"] = "auto"

    # ── Cost-step provider override ──────────────────────────
    # The cost estimator is text-only, so it can run on a different (cheaper)
    # model than the vision step.
    # "auto"      — follow llm_provider (default, previous behaviour)
    # "bedrock"   — Qwen3-32B on Bedrock
    # "openai"    — openai_cost_model
    # "fireworks" — an open-weight model on Fireworks AI (e.g. GPT-OSS)
    # Not added to llm_provider itself because Fireworks serves GPT-OSS as a
    # text-only model — it cannot do the vision step.
    cost_llm_provider: Literal["auto", "bedrock", "openai", "fireworks"] = "auto"

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

    # ── Fireworks AI — GPT-OSS for cost estimation ────────────
    # Only required when cost_llm_provider=fireworks.
    # Fireworks exposes an OpenAI-compatible /chat/completions endpoint, so the
    # existing `openai` SDK is reused with a different base_url — no new
    # dependency.
    fireworks_api_key: str = ""
    fireworks_base_url: str = "https://api.fireworks.ai/inference/v1"
    fireworks_cost_model: str = "accounts/fireworks/models/gpt-oss-120b"

    # Vision model for the damage-detection step. Must be multimodal, so unlike
    # the cost step this cannot use GPT-OSS.
    # qwen3p8-max is available on serverless and verified on car-damage photos.
    # qwen3p8-flash-next-nvfp4 is NOT on serverless (404) — it needs an
    # on-demand deployment, referenced as "<model-id>#<deployment-name>".
    fireworks_vision_model: str = "accounts/fireworks/models/qwen3p8-max"

    # Reasoning tokens count against this. Measured on a real damage photo,
    # qwen3p8-max emits no JSON at 2048 or 4096 and needs 8192; kimi-k3 works
    # at 4096. Too low fails the vision step outright.
    fireworks_vision_max_tokens: int = 8192

    # GPT-OSS is a reasoning model: it spends tokens thinking before it answers.
    # "none" omits the parameter entirely (for non-reasoning models).
    fireworks_reasoning_effort: Literal["none", "low", "medium", "high"] = "low"

    # Reasoning tokens count against max_tokens, so the cost call needs far more
    # headroom than the 500 that suffices for GPT-4o. Too low truncates the JSON.
    fireworks_cost_max_tokens: int = 2048

    # Ask Fireworks to constrain decoding to valid JSON. Set false if the model
    # or deployment rejects response_format.
    fireworks_json_mode: bool = True

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

    # ── Analysis mode ─────────────────────────────────────────
    # "inline" — ClaimLens runs vision + cost directly in-process (default).
    # "agents" — ClaimLens delegates to the Agentex multi-agent orchestrator
    #            (Orchestrator → Damage Detection agent → Cost Estimation agent).
    #            Requires the Agentex stack + claim-analyzer agent running.
    analysis_mode: Literal["inline", "agents"] = "inline"

    # Agentex backend RPC base (used only when analysis_mode=agents)
    agentex_base_url: str = "http://localhost:5003"
    agentex_agent_name: str = "claim-analyzer"

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

    @property
    def effective_vision_provider(self) -> str:
        """
        Provider the vision step should use: vision_llm_provider when set
        explicitly, otherwise whatever llm_provider says.
        """
        if self.vision_llm_provider == "auto":
            return self.llm_provider
        return self.vision_llm_provider

    @property
    def vision_model_name(self) -> str:
        """Model id the vision step will call, for logs and eval banners."""
        return {
            "bedrock": self.bedrock_vision_model_id,
            "openai": self.openai_vision_model,
            "fireworks": self.fireworks_vision_model,
        }.get(self.effective_vision_provider, "unknown")

    @property
    def effective_cost_provider(self) -> str:
        """
        Provider the cost estimator should use: cost_llm_provider when set
        explicitly, otherwise whatever llm_provider says.
        """
        if self.cost_llm_provider == "auto":
            return self.llm_provider
        return self.cost_llm_provider

    @property
    def cost_model_name(self) -> str:
        """Model id the cost estimator will call, for logs and eval banners."""
        return {
            "bedrock": self.bedrock_cost_model_id,
            "openai": self.openai_cost_model,
            "fireworks": self.fireworks_cost_model,
        }.get(self.effective_cost_provider, "unknown")


# Singleton — import this everywhere
settings = Settings()

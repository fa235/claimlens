"""
ClaimLens — FastAPI application entry point.

Start locally:
    uvicorn app.main:app --reload --port 8000

API docs (auto-generated):
    http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from app.core.config import settings
from app.api.routes import router
from app.models.database import Base, engine

# ── Create all tables on startup (dev convenience) ────────────────────────────
# In production, use Alembic migrations instead:
#   alembic upgrade head
Base.metadata.create_all(bind=engine)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    description="Car damage analysis API — color, model, damage detection, repair cost estimate.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# In development, allow the Vite dev server.
# In production, restrict to your actual domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static files (local uploads) ──────────────────────────────────────────────
# Serves uploaded images at /uploads/<filename>
# Only mounted when using local storage
if settings.storage_backend == "local":
    os.makedirs(settings.upload_dir, exist_ok=True)
    app.mount(
        "/uploads",
        StaticFiles(directory=settings.upload_dir),
        name="uploads",
    )
else:
    # S3 backend: the bucket is private, so stream images through the API.
    # Same /uploads/<key> URL shape as local storage, so the frontend is
    # unchanged.
    from fastapi import HTTPException
    from fastapi.responses import StreamingResponse
    from app.services.storage import storage

    @app.get("/uploads/{key:path}", tags=["uploads"])
    def get_upload(key: str):
        # Only serve claim images; block traversal / other bucket objects.
        if not key.startswith("claims/") or ".." in key:
            raise HTTPException(status_code=404, detail="Image not found.")
        body, content_type = storage.open(key)
        return StreamingResponse(
            body.iter_chunks(chunk_size=64 * 1024),
            media_type=content_type,
            headers={"Cache-Control": "private, max-age=86400"},
        )

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(router)


@app.get("/health", tags=["health"])
def health_check():
    """Simple liveness check for load balancers and monitoring."""
    return {"status": "ok", "service": settings.app_name}

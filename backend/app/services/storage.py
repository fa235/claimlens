"""
Storage service — abstracts local disk vs AWS S3.

Usage:
    from app.services.storage import storage
    url = await storage.save(file_bytes, filename)

Switch backends by setting STORAGE_BACKEND=local or STORAGE_BACKEND=s3 in .env
"""

import os
import uuid
import aiofiles
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException

from app.core.config import settings


def _unique_filename(original: str) -> str:
    """Prefix original filename with a UUID to avoid collisions."""
    ext = os.path.splitext(original)[-1].lower()
    return f"{uuid.uuid4().hex}{ext}"


# ── Local storage ─────────────────────────────────────────────────────────────

class LocalStorage:
    """Saves files to the local uploads/ directory."""

    def __init__(self, upload_dir: str):
        self.upload_dir = upload_dir
        os.makedirs(upload_dir, exist_ok=True)

    async def save(self, file_bytes: bytes, original_filename: str) -> str:
        """
        Saves file to disk and returns a URL path (relative, served by FastAPI).
        """
        filename = _unique_filename(original_filename)
        dest = os.path.join(self.upload_dir, filename)

        async with aiofiles.open(dest, "wb") as f:
            await f.write(file_bytes)

        # Return a URL that FastAPI will serve via StaticFiles
        return f"/uploads/{filename}"

    async def delete(self, url: str) -> None:
        filename = url.split("/")[-1]
        path = os.path.join(self.upload_dir, filename)
        if os.path.exists(path):
            os.remove(path)


# ── S3 storage ────────────────────────────────────────────────────────────────

class S3Storage:
    """Saves files to an AWS S3 bucket and returns a public URL."""

    def __init__(self):
        # Only pass explicit static credentials when BOTH are actually set
        # (e.g. local dev). In AWS (ECS/Fargate) we rely on the task role via
        # boto3's default credential chain — passing empty strings here would
        # produce an "AuthorizationHeaderMalformed" error, so we must omit them.
        client_kwargs = {"region_name": settings.aws_region}
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = settings.aws_access_key_id
            client_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

        self.client = boto3.client("s3", **client_kwargs)
        self.bucket = settings.s3_bucket

    async def save(self, file_bytes: bytes, original_filename: str) -> str:
        """
        Uploads file to S3 and returns the public HTTPS URL.
        """
        if not self.bucket:
            raise HTTPException(status_code=500, detail="S3_BUCKET is not configured.")

        filename = _unique_filename(original_filename)
        key = f"claims/{filename}"

        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=file_bytes,
                ContentType="image/jpeg",
            )
        except (BotoCoreError, ClientError) as e:
            raise HTTPException(status_code=500, detail=f"S3 upload failed: {e}")

        # The bucket blocks public access. Return a short, stable app-relative
        # path; the backend's /uploads/{key} route streams the object from S3.
        # (Presigned URLs were too long for the DB column and expire.)
        return f"/uploads/{key}"

    def open(self, key: str):
        """
        Fetch an object for streaming. Returns (body_stream, content_type),
        or raises HTTPException(404) if it doesn't exist.
        """
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                raise HTTPException(status_code=404, detail="Image not found.")
            raise HTTPException(status_code=502, detail="Could not load image.")
        return obj["Body"], obj.get("ContentType") or "image/jpeg"

    async def delete(self, url: str) -> None:
        # URL is "/uploads/claims/<filename>" → key "claims/<filename>".
        path = url.split("?", 1)[0]
        key = "/".join(path.split("/")[-2:])
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError):
            pass  # best-effort delete


# ── Factory ───────────────────────────────────────────────────────────────────

def _create_storage():
    if settings.storage_backend == "s3":
        return S3Storage()
    return LocalStorage(upload_dir=settings.upload_dir)


# Single instance — import this everywhere
storage = _create_storage()

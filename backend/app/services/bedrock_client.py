"""
AWS Bedrock client factory.

Provides a single boto3 bedrock-runtime client reused across services.
Credentials are read from environment variables / IAM role automatically
by boto3 — no explicit key handling needed when running on ECS with a
task role, or when AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY are set.
"""

import boto3
from functools import lru_cache
from app.core.config import settings


@lru_cache(maxsize=1)
def get_bedrock_client():
    """Returns a cached boto3 bedrock-runtime client."""
    kwargs = {"region_name": settings.aws_region}

    # Explicit credentials only needed in local dev
    # On ECS/SageMaker, the IAM task role is used automatically
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"]     = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

    return boto3.client("bedrock-runtime", **kwargs)

from functools import lru_cache
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from django.conf import settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

UPLOAD_URL_SECONDS = 600
_REGION = "us-east-1"
_SIGNING = {"signature_version": "s3v4", "s3": {"addressing_style": "path"}}


def _client(endpoint_url: str, config: Config) -> S3Client:
    # A session per client: boto3's shared default session isn't safe to create from two threads.
    return boto3.session.Session().client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        region_name=_REGION,
        config=config,
    )


@lru_cache(maxsize=1)
def internal_client() -> S3Client:
    """For chatty-core's own calls (head, copy, delete). Blocking: call it through sync_to_async."""
    config = Config(**_SIGNING, connect_timeout=2, read_timeout=5, retries={"max_attempts": 2})
    return _client(settings.MINIO_INTERNAL_URL, config)


@lru_cache(maxsize=1)
def public_client() -> S3Client:
    """Only signs URLs, for the address the browser reaches. Signing makes no network call."""
    return _client(settings.MINIO_PUBLIC_URL, Config(**_SIGNING))


def presign_put(key: str, mime: str, size: int, expires: int = UPLOAD_URL_SECONDS) -> str:
    """PUT URL for key that accepts only this Content-Type and Content-Length. Never log it."""
    return public_client().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.MINIO_BUCKET,
            "Key": key,
            "ContentType": mime,
            "ContentLength": size,
        },
        ExpiresIn=expires,
        HttpMethod="PUT",
    )

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

UPLOAD_URL_SECONDS = 600
READ_START_BYTES = 8192  # what filetype looks at

_REGION = "us-east-1"
_SIGNING = {"signature_version": "s3v4", "s3": {"addressing_style": "path"}}


@dataclass(frozen=True)
class ObjectInfo:
    size: int
    content_type: str


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


def head(key: str) -> ObjectInfo | None:
    """Size and Content-Type of an object, or None if it doesn't exist."""
    try:
        response = internal_client().head_object(Bucket=settings.MINIO_BUCKET, Key=key)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise
    return ObjectInfo(size=response["ContentLength"], content_type=response.get("ContentType", ""))


def read_start(key: str, size: int = READ_START_BYTES) -> bytes:
    """The first bytes of an object, or all of it if it is shorter."""
    response = internal_client().get_object(
        Bucket=settings.MINIO_BUCKET, Key=key, Range=f"bytes=0-{size - 1}"
    )
    with response["Body"] as body:
        return body.read()


def read_all(key: str) -> bytes:
    """The whole object, in memory. Only for small files (avatars and team icons, max 2 MB)."""
    response = internal_client().get_object(Bucket=settings.MINIO_BUCKET, Key=key)
    with response["Body"] as body:
        return body.read()


def copy(source: str, target: str) -> None:
    """Copy inside the bucket, without downloading. Content-Type comes along."""
    bucket = settings.MINIO_BUCKET
    internal_client().copy_object(
        Bucket=bucket, Key=target, CopySource={"Bucket": bucket, "Key": source}
    )


def delete(*keys: str) -> None:
    """Delete objects in one call. A key that doesn't exist is not an error."""
    if not keys:
        return
    response = internal_client().delete_objects(
        Bucket=settings.MINIO_BUCKET,
        Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
    )
    errors = response.get("Errors")
    if errors:
        raise RuntimeError(f"MinIO could not delete {[e.get('Key') for e in errors]}")

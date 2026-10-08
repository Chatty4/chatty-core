import logging
import uuid
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions as drf
from rest_framework.response import Response

from shared.exceptions import (
    AppError,
    InternalError,
    NotFound,
    PermissionDenied,
    RateLimited,
    Unauthorized,
    ValidationFailed,
)

logger = logging.getLogger(__name__)

NON_FIELD = "non_field_errors"

# DRF validation codes that the contract names differently; all others pass through.
FIELD_CODES = {"max_length": "too_long", "min_length": "too_short"}


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response:
    """DRF EXCEPTION_HANDLER: every error leaves the API in the contract shape."""
    error = _to_app_error(exc)

    body: dict[str, Any] = {"code": str(error.code), "message": error.message}
    if error.fields:
        body["fields"] = error.fields
    if error.status_code == 500:
        body["request_id"] = _log_unhandled(exc)

    headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
    return Response({"error": body}, status=error.status_code, headers=headers)


def _to_app_error(exc: Exception) -> AppError:
    """Turn any exception into an AppError, so there is one way to build the response."""
    if isinstance(exc, AppError):
        return exc
    if isinstance(exc, drf.ValidationError):
        return ValidationFailed(fields=_collect_fields(exc.detail))
    if isinstance(exc, drf.Throttled):
        wait = getattr(exc, "wait", None)  # set by DRF;
        return RateLimited(retry_after=max(1, wait or 1))
    if isinstance(exc, drf.NotAuthenticated | drf.AuthenticationFailed):
        return Unauthorized()
    if isinstance(exc, drf.PermissionDenied | DjangoPermissionDenied):
        return PermissionDenied()
    if isinstance(exc, Http404):
        return NotFound("not_found")
    if isinstance(exc, drf.APIException):  # 405, 406, 415, malformed JSON, ...
        return AppError(exc.default_code, str(exc.detail), status_code=exc.status_code)
    return InternalError()


def _log_unhandled(exc: Exception) -> str:
    """A bug: log it with an id. The client only gets the id, never the details."""
    request_id = uuid.uuid4().hex
    logger.error("Unhandled error (request_id=%s)", request_id, exc_info=exc)
    return request_id


def _collect_fields(detail: Any, path: str = "") -> dict[str, str]:
    """Flatten DRF's error detail into {field path: reason}, one reason per field.

    Nested serializers give "address.city", many=True items give "items.0.name", and errors
    that belong to no field use "non_field_errors".
    """
    messages = detail if isinstance(detail, list) else [detail]
    if messages and all(isinstance(m, drf.ErrorDetail) for m in messages):
        reason = messages[0].code or "invalid"
        return {path or NON_FIELD: FIELD_CODES.get(reason, reason)}

    # Nested errors: a dict keyed by field name, or a list with one entry per item.
    children = detail.items() if isinstance(detail, dict) else enumerate(detail)
    fields: dict[str, str] = {}
    for key, child in children:
        fields |= _collect_fields(child, f"{path}.{key}" if path else str(key))
    return fields

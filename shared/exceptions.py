"""
Services raise these, never DRF exceptions or HTTP responses. The exception handler in
shared/exception_handler.py turns them into the contract error body:
{"error": {"code", "message", "fields"?}}.

Codes come from shared/codes.py. Some classes have a default code. BadRequest, NotFound, Conflict
and Gone have many codes in the contract, so the caller must pass one:
    raise NotFound(ErrorCode.TEAM_NOT_FOUND)
"""

from shared.codes import ErrorCode


class AppError(Exception):
    status_code: int = 500
    code: str | None = None
    message: str = "Error"

    def __init__(
        self,
        code: str | None = None,
        message: str | None = None,
        *,
        fields: dict[str, str] | None = None,
        retry_after: int | None = None,
        status_code: int | None = None,
    ) -> None:
        self.code = code or self.code
        if self.code is None:
            raise TypeError(f"{type(self).__name__} needs an error code")
        self.message = message or self.message
        self.fields = fields or {}
        self.retry_after = retry_after
        if status_code:
            self.status_code = status_code
        super().__init__(self.message)


# Without a default code: the caller passes one.
class BadRequest(AppError):
    status_code = 400
    message = "Bad request"


class NotFound(AppError):
    status_code = 404
    message = "Not found"


class Conflict(AppError):
    status_code = 409
    message = "Conflict"


class Gone(AppError):
    status_code = 410
    message = "Gone"


# With a default code.
class ValidationFailed(AppError):
    """`fields` maps a field name to a reason, e.g. {"name": "too_long"}."""

    status_code = 400
    code = ErrorCode.VALIDATION_ERROR
    message = "Invalid request"


class Unauthorized(AppError):
    status_code = 401
    code = ErrorCode.UNAUTHORIZED
    message = "Authentication required"


class PermissionDenied(AppError):
    status_code = 403
    code = ErrorCode.FORBIDDEN
    message = "You are not allowed to do this"


class UserInactive(PermissionDenied):
    code = ErrorCode.USER_INACTIVE
    message = "This account has been deactivated"


class RateLimited(AppError):
    """`retry_after` (seconds) becomes the Retry-After header."""

    status_code = 429
    code = ErrorCode.RATE_LIMITED
    message = "Too many requests"

    def __init__(
        self, retry_after: int, code: str | None = None, message: str | None = None
    ) -> None:
        super().__init__(code, message, retry_after=retry_after)


class InternalError(AppError):
    status_code = 500
    code = ErrorCode.INTERNAL_ERROR
    message = "Internal server error"

import pytest

from shared.codes import ErrorCode
from shared.exceptions import (
    BadRequest,
    Conflict,
    Gone,
    NotFound,
    PermissionDenied,
    RateLimited,
    Unauthorized,
    UserInactive,
    ValidationFailed,
)


def test_defaults_and_code_override():
    assert PermissionDenied().code == "forbidden"
    assert PermissionDenied(code=ErrorCode.NOT_A_TEAM_MEMBER).code == "not_a_team_member"
    assert Unauthorized(code=ErrorCode.INVALID_CREDENTIALS).status_code == 401


def test_user_inactive_is_a_403_permission_error():
    error = UserInactive()
    assert isinstance(error, PermissionDenied)
    assert (error.status_code, error.code) == (403, "user_inactive")


def test_validation_failed_carries_fields():
    error = ValidationFailed(fields={"name": "too_long"})
    assert error.status_code == 400
    assert error.code == "validation_error"
    assert error.fields == {"name": "too_long"}


def test_rate_limited_carries_retry_after():
    error = RateLimited(retry_after=30, code=ErrorCode.TOO_MANY_ATTEMPTS)
    assert (error.status_code, error.code, error.retry_after) == (429, "too_many_attempts", 30)


@pytest.mark.parametrize(
    ("error_class", "status_code"),
    [(BadRequest, 400), (NotFound, 404), (Conflict, 409), (Gone, 410)],
)
def test_coded_errors_have_status_and_the_given_code(error_class, status_code):
    error = error_class(ErrorCode.INVITE_INVALID, "message")
    assert (error.status_code, error.code, error.message) == (
        status_code,
        "invite_invalid",
        "message",
    )


@pytest.mark.parametrize("error_class", [BadRequest, NotFound, Conflict, Gone])
def test_coded_errors_require_a_code(error_class):
    with pytest.raises(TypeError):
        error_class()

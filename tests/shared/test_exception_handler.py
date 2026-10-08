import logging

import pytest
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import serializers
from rest_framework.exceptions import (
    AuthenticationFailed,
    MethodNotAllowed,
    NotAuthenticated,
    ParseError,
    Throttled,
)

from shared.codes import ErrorCode
from shared.exception_handler import exception_handler
from shared.exceptions import Conflict, RateLimited, ValidationFailed


def handle(exc: Exception):
    return exception_handler(exc, {})


def fields_of(serializer: serializers.Serializer) -> dict[str, str]:
    with pytest.raises(serializers.ValidationError) as caught:
        serializer.is_valid(raise_exception=True)
    response = handle(caught.value)
    assert response.status_code == 400
    assert response.data["error"]["code"] == "validation_error"
    return response.data["error"]["fields"]


def test_app_error_uses_the_contract_body():
    response = handle(Conflict(ErrorCode.EMAIL_TAKEN, "Email already registered"))

    assert response.status_code == 409
    assert response.data == {
        "error": {"code": "email_taken", "message": "Email already registered"}
    }


def test_validation_failed_has_fields_only_when_given():
    response = handle(ValidationFailed(fields={"name": "too_long"}))

    assert response.data["error"]["fields"] == {"name": "too_long"}
    assert "fields" not in handle(ValidationFailed()).data["error"]


def test_rate_limited_sets_retry_after():
    response = handle(RateLimited(retry_after=30, code=ErrorCode.TOO_MANY_ATTEMPTS))

    assert response.status_code == 429
    assert response["Retry-After"] == "30"
    assert response.data["error"]["code"] == "too_many_attempts"


def test_drf_throttled_becomes_rate_limited():
    response = handle(Throttled(wait=10.2))

    assert response.status_code == 429
    assert response["Retry-After"] == "11"
    assert response.data["error"]["code"] == "rate_limited"


def test_drf_throttled_without_wait_still_sends_retry_after():
    assert handle(Throttled())["Retry-After"] == "1"


@pytest.mark.parametrize("exc", [NotAuthenticated(), AuthenticationFailed()])
def test_drf_auth_errors_become_unauthorized(exc):
    response = handle(exc)

    assert response.status_code == 401
    assert response.data["error"]["code"] == "unauthorized"


def test_django_permission_denied_becomes_forbidden():
    response = handle(DjangoPermissionDenied())

    assert response.status_code == 403
    assert response.data["error"]["code"] == "forbidden"


def test_http404_becomes_not_found():
    response = handle(Http404())

    assert response.status_code == 404
    assert response.data["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    ("exc", "status_code", "code"),
    [
        (MethodNotAllowed("POST"), 405, "method_not_allowed"),
        (ParseError(), 400, "parse_error"),
    ],
)
def test_other_drf_errors_keep_their_status(exc, status_code, code):
    response = handle(exc)

    assert response.status_code == status_code
    assert response.data["error"]["code"] == code


def test_unhandled_error_is_500_without_leaking_details(caplog):
    with caplog.at_level(logging.ERROR):
        response = handle(RuntimeError("secret detail"))

    error = response.data["error"]
    assert response.status_code == 500
    assert error["code"] == "internal_error"
    assert "secret detail" not in str(response.data)
    assert error["request_id"] in caplog.text


class PersonSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=3, min_length=2)
    email = serializers.EmailField()


def test_validation_error_gives_one_reason_per_field():
    fields = fields_of(PersonSerializer(data={"name": "toolong"}))

    assert fields == {"name": "too_long", "email": "required"}


def test_validation_error_too_short():
    fields = fields_of(PersonSerializer(data={"name": "x", "email": "a@b.co"}))

    assert fields == {"name": "too_short"}


def test_validation_error_for_a_nested_serializer_uses_a_dotted_path():
    class OrderSerializer(serializers.Serializer):
        person = PersonSerializer()

    fields = fields_of(OrderSerializer(data={"person": {"name": "ok"}}))

    assert fields == {"person.email": "required"}


def test_validation_error_for_many_items_uses_the_item_index():
    class ListSerializer(serializers.Serializer):
        people = PersonSerializer(many=True)

    data = {"people": [{"name": "ok", "email": "a@b.co"}, {"name": "ok"}]}

    assert fields_of(ListSerializer(data=data)) == {"people.1.email": "required"}


def test_validation_error_without_a_field_uses_non_field_errors():
    class PasswordsSerializer(serializers.Serializer):
        def validate(self, attrs):
            raise serializers.ValidationError("passwords differ", code="mismatch")

    assert fields_of(PasswordsSerializer(data={})) == {"non_field_errors": "mismatch"}

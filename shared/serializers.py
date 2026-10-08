from typing import Any

from rest_framework.serializers import BaseSerializer


def validated(serializer_class: type[BaseSerializer], data: Any, **kwargs: Any) -> Any:
    """Run a serializer on `data` and return its validated data.

    Invalid input raises DRF's ValidationError, which the exception handler turns into the
    contract's validation_error body. Extra keyword arguments go to the serializer
    (context=..., many=True, partial=True).
    """
    serializer = serializer_class(data=data, **kwargs)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data

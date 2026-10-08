import pytest
from rest_framework import serializers

from shared.serializers import validated


class PersonSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=3)


def test_returns_the_validated_data():
    assert validated(PersonSerializer, {"name": "ana", "ignored": 1}) == {"name": "ana"}


def test_invalid_data_raises_validation_error():
    with pytest.raises(serializers.ValidationError) as caught:
        validated(PersonSerializer, {"name": "toolong"})

    assert "name" in caught.value.detail


def test_extra_arguments_go_to_the_serializer():
    assert validated(PersonSerializer, [{"name": "a"}, {"name": "b"}], many=True) == [
        {"name": "a"},
        {"name": "b"},
    ]

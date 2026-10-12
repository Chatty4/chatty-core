from django.test import RequestFactory

from shared.http import client_ip

factory = RequestFactory()


def test_ignores_header_when_not_behind_proxy(settings):
    settings.BEHIND_PROXY = False
    request = factory.get("/", HTTP_X_REAL_IP="1.2.3.4", REMOTE_ADDR="10.0.0.1")

    assert client_ip(request) == "10.0.0.1"


def test_uses_header_behind_proxy(settings):
    settings.BEHIND_PROXY = True
    request = factory.get("/", HTTP_X_REAL_IP="1.2.3.4", REMOTE_ADDR="10.0.0.1")

    assert client_ip(request) == "1.2.3.4"


def test_falls_back_when_header_missing(settings):
    settings.BEHIND_PROXY = True
    request = factory.get("/", REMOTE_ADDR="10.0.0.1")

    assert client_ip(request) == "10.0.0.1"

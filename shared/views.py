import inspect
from typing import Any

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseBase
from rest_framework.views import APIView


class AsyncAPIView(APIView):
    """DRF APIView with `async def` handlers.

    Authentication, permissions and throttling (`initial`) are sync in DRF, so they run in a thread.
    """

    async def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        self.args = args
        self.kwargs = kwargs
        drf_request = self.initialize_request(request, *args, **kwargs)
        self.request = drf_request
        self.headers = self.default_response_headers

        try:
            await sync_to_async(self.initial)(drf_request, *args, **kwargs)
            method = (drf_request.method or "").lower()
            if method in self.http_method_names:
                handler = getattr(self, method, self.http_method_not_allowed)
            else:
                handler = self.http_method_not_allowed
            response = handler(drf_request, *args, **kwargs)
            if inspect.isawaitable(response):  # DRF's options() is sync
                response = await response
        except Exception as exc:
            response = await sync_to_async(self.handle_exception)(exc)

        self.response = self.finalize_response(drf_request, response, *args, **kwargs)
        return self.response

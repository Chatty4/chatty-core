from rest_framework.response import Response

from files.internal.serializers import AttachRequest, AttachResponse
from files.services import FileService
from shared.serializers import validated
from shared.views import InternalAPIView


class FileAttachView(InternalAPIView):
    async def post(self, request):
        data = validated(AttachRequest, request.data)
        files = await FileService.attach(**data)
        return Response(AttachResponse({"attachments": files}).data)

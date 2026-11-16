from uuid import UUID

from rest_framework.response import Response

from files.serializers import CreateFileRequest, FileResponse, UploadResponse
from files.services import FileService
from shared.serializers import validated
from shared.views import AsyncAPIView


class FilesView(AsyncAPIView):
    async def post(self, request):
        data = validated(CreateFileRequest, request.data)
        result = await FileService.create_upload(**data, user_id=request.user.id)
        return Response(UploadResponse(result).data, status=201)


class FileConfirmView(AsyncAPIView):
    async def post(self, request, file_id: UUID):
        file = await FileService.confirm(file_id, request.user.id)
        return Response(FileResponse(file).data)


class FileDetailView(AsyncAPIView):
    async def get(self, request, file_id: UUID):
        url = await FileService.download_url(file_id, request.user.id)
        return Response(status=302, headers={"Location": url})

from django.urls import path

from files.views import FileConfirmView, FileDetailView, FilesView

urlpatterns = [
    path("files", FilesView.as_view(), name="files"),
    path("files/<uuid:file_id>", FileDetailView.as_view(), name="file-detail"),
    path("files/<uuid:file_id>/confirm", FileConfirmView.as_view(), name="file-confirm"),
]

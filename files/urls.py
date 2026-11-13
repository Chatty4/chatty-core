from django.urls import path

from files.views import FileConfirmView, FilesView

urlpatterns = [
    path("files", FilesView.as_view(), name="files"),
    path("files/<uuid:file_id>/confirm", FileConfirmView.as_view(), name="file-confirm"),
]

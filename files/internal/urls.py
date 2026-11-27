from django.urls import path

from files.internal.views import FileAttachView, FileCopyView, FileDetachView

urlpatterns = [
    path("files/attach", FileAttachView.as_view(), name="internal-file-attach"),
    path("files/detach", FileDetachView.as_view(), name="internal-file-detach"),
    path("files/copy", FileCopyView.as_view(), name="internal-file-copy"),
]

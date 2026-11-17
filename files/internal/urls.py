from django.urls import path

from files.internal.views import FileAttachView

urlpatterns = [
    path("files/attach", FileAttachView.as_view(), name="internal-file-attach"),
]

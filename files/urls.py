from django.urls import path

from files.views import FilesView

urlpatterns = [
    path("files", FilesView.as_view(), name="files"),
]

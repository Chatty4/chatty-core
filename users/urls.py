from django.urls import path

from users.views import LoginView, RegisterView

urlpatterns = [
    path("auth/register", RegisterView.as_view()),
    path("auth/login", LoginView.as_view()),
]

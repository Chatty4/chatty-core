from django.urls import path

from users.views import ChangePasswordView, LoginView, MeView, RegisterView

urlpatterns = [
    path("auth/register", RegisterView.as_view()),
    path("auth/login", LoginView.as_view()),
    path("auth/password", ChangePasswordView.as_view()),
    path("me", MeView.as_view()),
]

from django.urls import path

from users.views import LoginView, LogoutView, MeView, RefreshTokenView, RegisterView

urlpatterns = [
    path("auth/register", RegisterView.as_view()),
    path("auth/login", LoginView.as_view()),
    path("auth/refresh", RefreshTokenView.as_view()),
    path("auth/logout", LogoutView.as_view()),
    path("me", MeView.as_view()),
]

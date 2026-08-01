from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="portal/login.html", redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("clients/<int:pk>/", views.client_detail, name="client_detail"),
    path("review/", views.review_queue, name="review_queue"),
    path("review/<int:pk>/resolve/", views.review_resolve, name="review_resolve"),
    path("intake/", views.intake, name="intake"),
    path("intake/batch/<int:pk>/", views.batch_detail, name="batch_detail"),
    path("reminders/", views.reminders_view, name="reminders"),
    path("settings/", views.settings_view, name="settings"),
]

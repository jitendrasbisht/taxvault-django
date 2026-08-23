from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="portal/login.html", redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("clients/", views.clients_list, name="clients_list"),
    path("clients/import/", views.import_clients_view, name="import_clients"),
    path("clients/add/", views.manual_add_client_view, name="manual_add_client"),
    path("clients/delete/", views.delete_clients_view, name="delete_clients"),
    path("clients/<int:pk>/", views.client_detail, name="client_detail"),
    path("clients/<int:pk>/edit/", views.edit_client_view, name="edit_client"),
    path("review/", views.review_queue, name="review_queue"),
    path("review/<int:pk>/resolve/", views.review_resolve, name="review_resolve"),
    path("intake/", views.intake, name="intake"),
    path("intake/upload/", views.intake_upload_view, name="intake_upload"),
    path("intake/batch/<int:pk>/", views.batch_detail, name="batch_detail"),
    path("intake/clear-all/", views.clear_all_batches_view, name="clear_all_batches"),
    path("intake/delete/", views.delete_batches_view, name="delete_batches"),
    path("reminders/", views.reminders_view, name="reminders"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/clear-all-clients/", views.clear_all_clients_view, name="clear_all_clients"),
    path("about/", views.about_view, name="about"),
]

import io
import zipfile

from django.contrib import admin, messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path
from django.utils.html import format_html

from .forms import FirmUserAddForm, ManualClientAddForm, ResetPasswordForm
from .models import Category, Client, DocCode, Firm, ReminderLog, UserProfile
from .reminders import send_followup, send_initial_request
from .services import ClientDataError, FirmUserError, create_firm_user, reset_firm_user_password, upsert_client

# documents depends on clients, never the reverse for models — but admin.py loads after
# all apps' models are ready, so this cross-app import here is safe.
from documents.models import Document
from documents.status import compute_itr_status
from documents.storage import absolute_path


def _get_profile(request):
    return getattr(request.user, "profile", None)


def _is_firm_admin(request):
    profile = _get_profile(request)
    return request.user.is_superuser or (profile is not None and profile.role == UserProfile.ROLE_FIRM_ADMIN)


class FirmScopedAdminMixin:
    """Section 13: enforce firm isolation at the query layer, not just the UI. Django
    superusers (the internal system admin, distinct from the in-app Firm Admin role) see
    everything; any other logged-in user only ever sees their own firm's rows — including
    detail/change views, since those also route through get_queryset()."""

    firm_field = "firm"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        profile = _get_profile(request)
        if not profile:
            return qs.none()
        return qs.filter(**{self.firm_field: profile.firm})

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == self.firm_field and not request.user.is_superuser:
            profile = _get_profile(request)
            if profile:
                kwargs["queryset"] = Firm.objects.filter(pk=profile.firm_id)
                kwargs["initial"] = profile.firm_id
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            profile = _get_profile(request)
            if profile:
                setattr(obj, self.firm_field, profile.firm)
        super().save_model(request, obj, form, change)


class ProfileRequiredMixin:
    """Any logged-in user with a profile (either role) gets access — used for Client, which
    both Firm Admin and Staff can see per Section 14's access table."""

    def _allowed(self, request):
        return request.user.is_superuser or _get_profile(request) is not None

    def has_module_permission(self, request):
        return self._allowed(request)

    def has_view_permission(self, request, obj=None):
        return self._allowed(request)

    def has_add_permission(self, request):
        return self._allowed(request)

    def has_change_permission(self, request, obj=None):
        return self._allowed(request)

    def has_delete_permission(self, request, obj=None):
        return self._allowed(request)


class FirmAdminOnlyMixin:
    """Firm settings (DocCode table, category mappings, staff management) are Firm Admin
    only — Staff has no access at all per Section 14's access table."""

    def _allowed(self, request):
        return _is_firm_admin(request)

    def has_module_permission(self, request):
        return self._allowed(request)

    def has_view_permission(self, request, obj=None):
        return self._allowed(request)

    def has_add_permission(self, request):
        return self._allowed(request)

    def has_change_permission(self, request, obj=None):
        return self._allowed(request)

    def has_delete_permission(self, request, obj=None):
        return self._allowed(request)


class SuperuserOnlyMixin:
    """Section 13: new firms are added manually by the system admin — an internal action,
    not something either in-app role (Firm Admin or Staff) can do."""

    def _allowed(self, request):
        return request.user.is_superuser

    def has_module_permission(self, request):
        return self._allowed(request)

    def has_view_permission(self, request, obj=None):
        return self._allowed(request)

    def has_add_permission(self, request):
        return self._allowed(request)

    def has_change_permission(self, request, obj=None):
        return self._allowed(request)

    def has_delete_permission(self, request, obj=None):
        return self._allowed(request)


class FirmScopedCategoryFilter(admin.SimpleListFilter):
    """A plain list_filter=("categories",) would list every firm's category names in the
    sidebar regardless of who's looking — Section 13 bars exactly that kind of leak."""

    title = "category"
    parameter_name = "category"

    def lookups(self, request, model_admin):
        qs = Category.objects.all()
        if not request.user.is_superuser:
            profile = _get_profile(request)
            qs = qs.filter(firm=profile.firm) if profile else qs.none()
        return [(c.id, c.name) for c in qs.order_by("name")]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(categories__id=self.value())
        return queryset


class ITRStatusFilter(admin.SimpleListFilter):
    """Section 9: Ready / In Progress / Not Started, for the current AY only — no AY
    switcher in MVP1 (Section 8), so this filter doesn't take one either."""

    title = "ITR status"
    parameter_name = "itr_status"

    def lookups(self, request, model_admin):
        return [("ready", "Ready"), ("in_progress", "In Progress"), ("not_started", "Not Started")]

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset
        matching_ids = [c.id for c in queryset if compute_itr_status(c).status == value]
        return queryset.filter(id__in=matching_ids)


@admin.register(Firm)
class FirmAdmin(SuperuserOnlyMixin, admin.ModelAdmin):
    list_display = ("name", "created_at")


@admin.register(DocCode)
class DocCodeAdmin(FirmAdminOnlyMixin, FirmScopedAdminMixin, admin.ModelAdmin):
    list_display = ("code", "display_name", "firm", "is_base")
    list_filter = ("is_base",)
    search_fields = ("code", "display_name")


@admin.register(Category)
class CategoryAdmin(FirmAdminOnlyMixin, FirmScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "firm")
    filter_horizontal = ("doc_codes",)


@admin.register(Client)
class ClientAdmin(ProfileRequiredMixin, FirmScopedAdminMixin, admin.ModelAdmin):
    list_display = ("pan", "name", "phone", "email", "firm", "aadhar_masked", "itr_status_display", "download_all_link")
    list_filter = (FirmScopedCategoryFilter, ITRStatusFilter)
    search_fields = ("pan", "name", "phone")
    actions = ["send_initial_request_action", "send_followup_action"]

    @admin.display(description="ITR Status")
    def itr_status_display(self, obj):
        return compute_itr_status(obj).label

    @admin.action(description="Section 11 Stage 1: Send Initial Request")
    def send_initial_request_action(self, request, queryset):
        count = 0
        for client in queryset:
            send_initial_request(client, sent_by=request.user)
            count += 1
        messages.success(request, f"Sent initial request to {count} client(s).")

    @admin.action(description="Section 11 Stage 2: Send Follow-up Reminder")
    def send_followup_action(self, request, queryset):
        sent, skipped = 0, 0
        for client in queryset:
            if send_followup(client, sent_by=request.user):
                sent += 1
            else:
                skipped += 1
        messages.success(request, f"Sent follow-up to {sent} client(s); {skipped} already Ready, skipped.")

    @admin.display(description="Documents")
    def download_all_link(self, obj):
        return format_html('<a href="{}/download-zip/">Download All</a>', obj.pk)

    def get_urls(self):
        custom_urls = [
            path("manual-add/", self.admin_site.admin_view(self.manual_add_view), name="clients_client_manual_add"),
            path("<int:pk>/download-zip/", self.admin_site.admin_view(self.download_zip_view), name="clients_client_download_zip"),
        ]
        return custom_urls + super().get_urls()

    def download_zip_view(self, request, pk):
        """Section 15: "Download all documents for a client" as a zip."""
        client = self.get_object(request, pk)
        if client is None:
            messages.error(request, "Client not found.")
            return redirect("admin:clients_client_changelist")

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            for doc in Document.objects.filter(client=client, status=Document.STATUS_FILED):
                file_path = absolute_path(doc.storage_path)
                if file_path.exists():
                    zf.write(file_path, arcname=file_path.name)
        buffer.seek(0)

        response = HttpResponse(buffer.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="{client.pan}_documents.zip"'
        return response

    def manual_add_view(self, request):
        """Manual individual add (Section 2) — same fields, routed through the same
        upsert_client service the bulk import path uses. Firm is locked to the logged-in
        user's own firm unless they're a superuser (Section 14 / Section 13 isolation)."""
        profile = _get_profile(request)
        locked_firm = profile.firm if profile else None

        if request.method == "POST":
            form = ManualClientAddForm(request.POST, locked_firm=locked_firm)
            if form.is_valid():
                cd = form.cleaned_data
                category_names = [c.name for c in cd["categories"]]
                try:
                    client, created = upsert_client(
                        cd["firm"], cd["pan"], cd["name"], cd["phone"], cd["email"], cd["aadhar"], category_names,
                        edited_by=request.user,
                    )
                except ClientDataError as exc:
                    form.add_error(None, str(exc))
                else:
                    verb = "Created" if created else "Updated"
                    messages.success(request, f"{verb} client {client.pan} — {client.name}.")
                    return redirect("admin:clients_client_changelist")
        else:
            form = ManualClientAddForm(locked_firm=locked_firm)

        context = {
            **self.admin_site.each_context(request),
            "form": form,
            "title": "Add Client (Manual)",
            "opts": self.model._meta,
        }
        return render(request, "admin/clients/client_manual_add.html", context)


@admin.register(UserProfile)
class UserProfileAdmin(FirmAdminOnlyMixin, FirmScopedAdminMixin, admin.ModelAdmin):
    """Staff management (Section 14) — Firm Admin only. Creation always goes through
    add_staff_view / create_firm_user(), never a raw ModelForm, since a real login (with a
    hashed password) has to be created alongside the profile."""

    list_display = ("user", "role", "firm", "reset_password_link")
    list_filter = ("role",)

    def has_add_permission(self, request):
        return False

    @admin.display(description="Password")
    def reset_password_link(self, obj):
        return format_html('<a href="{}/reset-password/">Reset password</a>', obj.pk)

    def get_urls(self):
        custom_urls = [
            path("add-staff/", self.admin_site.admin_view(self.add_staff_view), name="clients_userprofile_add_staff"),
            path("<int:pk>/reset-password/", self.admin_site.admin_view(self.reset_password_view), name="clients_userprofile_reset_password"),
        ]
        return custom_urls + super().get_urls()

    def reset_password_view(self, request, pk):
        profile = get_object_or_404(self.get_queryset(request), pk=pk)

        if request.method == "POST":
            form = ResetPasswordForm(request.POST)
            if form.is_valid():
                try:
                    reset_firm_user_password(profile, form.cleaned_data["new_password"])
                except FirmUserError as exc:
                    form.add_error(None, str(exc))
                else:
                    messages.success(request, f"Password reset for '{profile.user.username}'.")
                    return redirect("admin:clients_userprofile_changelist")
        else:
            form = ResetPasswordForm()

        context = {
            **self.admin_site.each_context(request),
            "form": form,
            "profile": profile,
            "title": f"Reset Password: {profile.user.username}",
            "opts": self.model._meta,
        }
        return render(request, "admin/clients/userprofile_reset_password.html", context)

    def add_staff_view(self, request):
        if not _is_firm_admin(request):
            messages.error(request, "You don't have permission to add staff.")
            return redirect("admin:index")

        profile = _get_profile(request)
        locked_firm = profile.firm if profile else None

        if request.method == "POST":
            form = FirmUserAddForm(request.POST, locked_firm=locked_firm)
            if form.is_valid():
                cd = form.cleaned_data
                try:
                    new_profile = create_firm_user(cd["firm"], cd["username"], cd["password"], cd["role"])
                except FirmUserError as exc:
                    form.add_error(None, str(exc))
                else:
                    messages.success(request, f"Created login '{new_profile.user.username}' ({new_profile.get_role_display()}).")
                    return redirect("admin:clients_userprofile_changelist")
        else:
            form = FirmUserAddForm(locked_firm=locked_firm)

        context = {
            **self.admin_site.each_context(request),
            "form": form,
            "title": "Add Staff",
            "opts": self.model._meta,
        }
        return render(request, "admin/clients/userprofile_add_staff.html", context)


@admin.register(ReminderLog)
class ReminderLogAdmin(ProfileRequiredMixin, FirmScopedAdminMixin, admin.ModelAdmin):
    """Section 11: read-only send log — visibility into reminder history. Entries are only
    ever created by an actual send (send_initial_request / send_followup), never by hand."""

    list_display = ("client", "stage", "sent_at", "firm")
    list_filter = ("stage",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

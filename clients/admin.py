from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path

from .forms import FirmUserAddForm, ManualClientAddForm
from .models import Category, Client, DocCode, Firm, UserProfile
from .services import ClientDataError, FirmUserError, create_firm_user, upsert_client


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
    list_display = ("pan", "name", "phone", "firm", "aadhar_masked")
    list_filter = (FirmScopedCategoryFilter,)
    search_fields = ("pan", "name", "phone")

    def get_urls(self):
        custom_urls = [
            path("manual-add/", self.admin_site.admin_view(self.manual_add_view), name="clients_client_manual_add"),
        ]
        return custom_urls + super().get_urls()

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
                        cd["firm"], cd["pan"], cd["name"], cd["phone"], cd["aadhar"], category_names
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

    list_display = ("user", "role", "firm")
    list_filter = ("role",)

    def has_add_permission(self, request):
        return False

    def get_urls(self):
        custom_urls = [
            path("add-staff/", self.admin_site.admin_view(self.add_staff_view), name="clients_userprofile_add_staff"),
        ]
        return custom_urls + super().get_urls()

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

from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path

from .forms import ManualClientAddForm
from .models import Category, Client, DocCode, Firm
from .services import ClientDataError, upsert_client


@admin.register(Firm)
class FirmAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")


@admin.register(DocCode)
class DocCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "display_name", "firm", "is_base")
    list_filter = ("firm", "is_base")
    search_fields = ("code", "display_name")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "firm")
    list_filter = ("firm",)
    filter_horizontal = ("doc_codes",)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("pan", "name", "phone", "firm", "aadhar_masked")
    list_filter = ("firm", "categories")
    search_fields = ("pan", "name", "phone")

    def get_urls(self):
        custom_urls = [
            path("manual-add/", self.admin_site.admin_view(self.manual_add_view), name="clients_client_manual_add"),
        ]
        return custom_urls + super().get_urls()

    def manual_add_view(self, request):
        """Manual individual add (Section 2) — same fields, routed through the same
        upsert_client service the bulk import path uses."""
        if request.method == "POST":
            form = ManualClientAddForm(request.POST)
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
            form = ManualClientAddForm()

        context = {
            **self.admin_site.each_context(request),
            "form": form,
            "title": "Add Client (Manual)",
            "opts": self.model._meta,
        }
        return render(request, "admin/clients/client_manual_add.html", context)

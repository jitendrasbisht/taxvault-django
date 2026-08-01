from django.contrib import admin

from .models import Category, Client, DocCode, Firm


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

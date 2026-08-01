from django.contrib import admin

from .models import Category, Client, Firm


@admin.register(Firm)
class FirmAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "firm")
    list_filter = ("firm",)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("pan", "name", "phone", "firm", "aadhar_masked")
    list_filter = ("firm", "categories")
    search_fields = ("pan", "name", "phone")

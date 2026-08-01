from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path

from clients.admin import FirmScopedAdminMixin, ProfileRequiredMixin

from .forms import ReviewResolutionForm
from .models import Batch, Document
from .services import ReviewResolutionError, resolve_review_document


@admin.register(Batch)
class BatchAdmin(ProfileRequiredMixin, FirmScopedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "firm", "ay", "files_found", "files_filed", "files_review", "files_skipped", "created_at")
    list_filter = ("ay",)

    def has_add_permission(self, request):
        # Batches are created by run_intake_batch / the future Django-Q trigger, not a
        # raw admin add form (folder_path shouldn't be freehand-typed against real storage).
        return False


@admin.register(Document)
class DocumentAdmin(ProfileRequiredMixin, FirmScopedAdminMixin, admin.ModelAdmin):
    list_display = ("original_filename", "client", "doc_code", "status", "ay", "firm", "review_reason")
    list_filter = ("status", "ay")
    search_fields = ("original_filename", "detected_pan")

    def has_add_permission(self, request):
        return False

    def get_urls(self):
        custom_urls = [
            path("<int:pk>/resolve/", self.admin_site.admin_view(self.resolve_view), name="documents_document_resolve"),
        ]
        return custom_urls + super().get_urls()

    def resolve_view(self, request, pk):
        document = get_object_or_404(self.get_queryset(request), pk=pk, review_reason__isnull=False)

        if request.method == "POST":
            form = ReviewResolutionForm(
                request.POST, firm=document.firm, client_locked=document.client is not None,
            )
            if form.is_valid():
                client = document.client if document.client is not None else form.cleaned_data["client"]
                doc_code = form.cleaned_data["doc_code"]
                try:
                    resolve_review_document(document, client, doc_code)
                except ReviewResolutionError as exc:
                    form.add_error(None, str(exc))
                else:
                    messages.success(request, f"Filed '{document.original_filename}' as {doc_code.code} for {client.name}.")
                    return redirect("admin:documents_document_changelist")
        else:
            form = ReviewResolutionForm(
                firm=document.firm, client_locked=document.client is not None,
                initial={"doc_code": document.doc_code_id},
            )

        context = {
            **self.admin_site.each_context(request),
            "form": form,
            "document": document,
            "title": f"Resolve: {document.original_filename}",
            "opts": self.model._meta,
        }
        return render(request, "admin/documents/document_resolve.html", context)

import mimetypes
from pathlib import Path

from django.contrib import admin, messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path
from django.utils.html import format_html
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django_q.tasks import async_task

from clients.admin import FirmScopedAdminMixin, ProfileRequiredMixin, _get_profile

from .forms import ReviewResolutionForm, StartBatchForm
from .models import Batch, Document
from .services import ReviewResolutionError, resolve_review_document
from .storage import absolute_path


@admin.register(Batch)
class BatchAdmin(ProfileRequiredMixin, FirmScopedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "firm", "ay", "files_found", "files_filed", "files_review", "files_skipped", "created_at")
    list_filter = ("ay",)

    def has_add_permission(self, request):
        # Batches are created via the Start Batch view (which also enqueues the Django-Q
        # task), not a raw admin add form -- folder_path shouldn't be freehand-typed
        # without also kicking off processing.
        return False

    def get_urls(self):
        custom_urls = [
            path("start/", self.admin_site.admin_view(self.start_batch_view), name="documents_batch_start"),
        ]
        return custom_urls + super().get_urls()

    def start_batch_view(self, request):
        profile = _get_profile(request)
        firm = profile.firm if profile else None
        if firm is None and not request.user.is_superuser:
            messages.error(request, "You don't have permission to start a batch.")
            return redirect("admin:index")

        if request.method == "POST":
            form = StartBatchForm(request.POST)
            if form.is_valid():
                folder = Path(form.cleaned_data["folder_path"])
                if not folder.is_dir():
                    form.add_error("folder_path", "Not a directory on this server.")
                else:
                    batch = Batch.objects.create(
                        firm=firm, ay=form.cleaned_data["ay"], folder_path=str(folder),
                        triggered_by=request.user,
                    )
                    async_task("documents.tasks.run_batch", batch.id)
                    messages.success(request, f"Batch #{batch.id} queued — refresh in a moment to see results.")
                    return redirect("admin:documents_batch_changelist")
        else:
            form = StartBatchForm()

        context = {
            **self.admin_site.each_context(request),
            "form": form,
            "title": "Start Batch",
            "opts": self.model._meta,
        }
        return render(request, "admin/documents/batch_start.html", context)


@admin.register(Document)
class DocumentAdmin(ProfileRequiredMixin, FirmScopedAdminMixin, admin.ModelAdmin):
    list_display = ("original_filename", "client", "doc_code", "status", "ay", "firm", "review_reason", "preview_link")
    list_filter = ("status", "ay")
    search_fields = ("original_filename", "detected_pan")

    def has_add_permission(self, request):
        return False

    @admin.display(description="Preview")
    def preview_link(self, obj):
        return format_html('<a href="{}/preview/" target="_blank">Preview</a>', obj.pk)

    def get_urls(self):
        custom_urls = [
            path("<int:pk>/resolve/", self.admin_site.admin_view(self.resolve_view), name="documents_document_resolve"),
            path("<int:pk>/preview/", self.admin_site.admin_view(self.preview_view), name="documents_document_preview"),
        ]
        return custom_urls + super().get_urls()

    @xframe_options_sameorigin
    def preview_view(self, request, pk):
        """Section 15: in-browser document preview (PDF/image). Serving the file with
        Content-Disposition: inline lets the browser's own PDF/image viewer render it —
        no custom viewer UI needed. X-Frame-Options relaxed to same-origin only (not
        exempt) so the portal's own resolve page can embed it in an iframe, while other
        sites still can't (clickjacking protection stays intact)."""
        document = get_object_or_404(self.get_queryset(request), pk=pk)
        file_path = absolute_path(document.storage_path)
        if not file_path.exists():
            raise Http404
        content_type, _ = mimetypes.guess_type(str(file_path))
        return FileResponse(
            open(file_path, "rb"),
            content_type=content_type or "application/octet-stream",
            filename=file_path.name,
            as_attachment=False,
        )

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

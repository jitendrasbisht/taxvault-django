import csv
import mimetypes
from pathlib import Path

import openpyxl
from django.contrib import admin, messages
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path
from django.utils.html import escape, format_html
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


_PREVIEW_MAX_ROWS = 500

_PREVIEW_STYLE = """
<style>
  body { font-family: -apple-system, "Segoe UI", sans-serif; margin: 0; padding: 16px; background: #fff; color: #1e293b; }
  h3 { font-size: 13px; color: #475569; margin: 20px 0 8px; }
  h3:first-child { margin-top: 0; }
  table { border-collapse: collapse; font-size: 12px; width: 100%; margin-bottom: 4px; }
  td { border: 1px solid #e2e8f0; padding: 4px 8px; text-align: left; white-space: nowrap; }
  tr:first-child td { font-weight: 600; background: #f8fafc; }
  .note { font-size: 11px; color: #94a3b8; margin-top: 4px; }
</style>
"""


def _render_spreadsheet_preview(file_path: Path) -> str:
    """Server-side HTML table view for .xlsx/.csv (Section 20 addendum): browsers have no
    native way to render a spreadsheet inline the way they do PDFs/images, so
    Content-Disposition: inline just triggers a download instead of a preview. Row count is
    capped since a 700-row bank statement dumped as one giant unstyled table isn't actually
    more useful than a reasonable preview -- this is a quick look, not a spreadsheet editor."""
    sheets = []
    truncated = False

    if file_path.suffix.lower() == ".csv":
        with open(file_path, newline="", encoding="utf-8-sig", errors="ignore") as f:
            rows = list(csv.reader(f))
        truncated = len(rows) > _PREVIEW_MAX_ROWS
        sheets.append((None, rows[:_PREVIEW_MAX_ROWS]))
    else:
        wb = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)
        try:
            for ws in wb.worksheets:
                rows = []
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i >= _PREVIEW_MAX_ROWS:
                        truncated = True
                        break
                    rows.append(["" if c is None else c for c in row])
                sheets.append((ws.title, rows))
        finally:
            wb.close()

    parts = [f"<!doctype html><html><head><meta charset='utf-8'>{_PREVIEW_STYLE}</head><body>"]
    for name, rows in sheets:
        if name:
            parts.append(f"<h3>{escape(name)}</h3>")
        parts.append("<table>")
        for row in rows:
            parts.append("<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>")
        parts.append("</table>")
    if truncated:
        parts.append(f"<p class='note'>Showing the first {_PREVIEW_MAX_ROWS} rows only.</p>")
    parts.append("</body></html>")
    return "".join(parts)


@admin.register(Document)
class DocumentAdmin(ProfileRequiredMixin, FirmScopedAdminMixin, admin.ModelAdmin):
    list_display = ("original_filename", "client", "doc_code", "status", "ay", "firm", "review_reason", "preview_link")
    list_filter = ("status", "ay")
    search_fields = ("original_filename", "detected_pan", "detected_account")

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
        if file_path.suffix.lower() in (".xlsx", ".csv"):
            return HttpResponse(_render_spreadsheet_preview(file_path))
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

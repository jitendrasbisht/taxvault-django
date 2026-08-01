from pathlib import Path

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django_q.tasks import async_task

from clients.models import Category, Client, DocCode, ReminderLog
from clients.reminders import send_followup, send_initial_request
from documents.models import Batch, Document
from documents.services import ReviewResolutionError, resolve_review_document
from documents.status import compute_itr_status
from taxvault.ay import current_assessment_year
from taxvault.vault_naming import vault_folder_path

from .auth import firm_admin_required, portal_view


@portal_view
def dashboard(request, profile):
    firm = profile.firm
    clients = Client.objects.filter(firm=firm).order_by("name")

    query = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "all")

    rows = []
    counts = {"ready": 0, "in_progress": 0, "not_started": 0}
    for client in clients:
        status = compute_itr_status(client)
        counts[status.status] += 1
        rows.append((client, status))

    if query:
        q_lower = query.lower()
        rows = [(c, s) for c, s in rows if q_lower in c.name.lower() or q_lower in c.pan.lower()]
    if status_filter != "all":
        rows = [(c, s) for c, s in rows if s.status == status_filter]

    context = {
        "active_nav": "dashboard",
        "profile": profile,
        "ay": current_assessment_year(),
        "rows": rows,
        "counts": counts,
        "total_clients": clients.count(),
        "query": query,
        "status_filter": status_filter,
    }
    return render(request, "portal/dashboard.html", context)


@portal_view
def client_detail(request, profile, pk):
    client = get_object_or_404(Client, pk=pk, firm=profile.firm)
    status = compute_itr_status(client)
    required = DocCode.objects.filter(firm=profile.firm, code__in=status.required_codes).order_by("code")
    received_docs = {
        d.doc_code.code: d
        for d in Document.objects.filter(client=client, ay=status.ay, status=Document.STATUS_FILED)
        .exclude(doc_code__code="MISC")
        .select_related("doc_code")
    }
    doc_rows = [(dc, received_docs.get(dc.code)) for dc in required]
    reminder_logs = ReminderLog.objects.filter(client=client).order_by("-sent_at")[:10]

    received_count = len(status.required_codes & status.received_codes)
    total_count = len(status.required_codes)
    progress_pct = int(100 * received_count / total_count) if total_count else 0
    vault_folder_relative = vault_folder_path(client.pan, client.name, status.ay)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "send_initial":
            send_initial_request(client)
            messages.success(request, f"Sent initial request to {client.name}.")
        elif action == "send_followup":
            if send_followup(client):
                messages.success(request, f"Sent follow-up to {client.name}.")
            else:
                messages.info(request, f"{client.name} is already Ready — no follow-up sent.")
        return redirect("portal:client_detail", pk=pk)

    context = {
        "active_nav": "dashboard",
        "profile": profile,
        "client": client,
        "status": status,
        "doc_rows": doc_rows,
        "reminder_logs": reminder_logs,
        "received_count": received_count,
        "total_count": total_count,
        "progress_pct": progress_pct,
        "vault_folder_relative": vault_folder_relative,
    }
    return render(request, "portal/client_detail.html", context)


@portal_view
def review_queue(request, profile):
    documents = (
        Document.objects.filter(firm=profile.firm, review_reason__isnull=False)
        .select_related("client", "doc_code")
        .order_by("id")
    )
    context = {"active_nav": "review", "profile": profile, "documents": documents}
    return render(request, "portal/review_queue.html", context)


@portal_view
def review_resolve(request, profile, pk):
    document = get_object_or_404(Document, pk=pk, firm=profile.firm, review_reason__isnull=False)
    clients = Client.objects.filter(firm=profile.firm).order_by("name")
    doc_codes = DocCode.objects.filter(firm=profile.firm).order_by("code")

    if request.method == "POST":
        client_id = document.client_id or request.POST.get("client")
        doc_code_id = request.POST.get("doc_code")
        client = get_object_or_404(Client, pk=client_id, firm=profile.firm) if client_id else None
        doc_code = get_object_or_404(DocCode, pk=doc_code_id, firm=profile.firm) if doc_code_id else None
        try:
            resolve_review_document(document, client, doc_code)
        except ReviewResolutionError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Filed '{document.original_filename}' as {doc_code.code} for {client.name}.")
            return redirect("portal:review_queue")

    context = {
        "active_nav": "review",
        "profile": profile,
        "document": document,
        "clients": clients,
        "doc_codes": doc_codes,
    }
    return render(request, "portal/review_resolve.html", context)


@portal_view
def intake(request, profile):
    if request.method == "POST":
        folder_path = request.POST.get("folder_path", "").strip()
        ay = request.POST.get("ay", "").strip() or current_assessment_year()
        folder = Path(folder_path)
        if not folder.is_dir():
            messages.error(request, f"Not a directory on this server: {folder_path}")
            return redirect("portal:intake")
        batch = Batch.objects.create(firm=profile.firm, ay=ay, folder_path=str(folder), triggered_by=request.user)
        async_task("documents.tasks.run_batch", batch.id)
        messages.success(request, f"Batch #{batch.id} queued.")
        return redirect("portal:batch_detail", pk=batch.id)

    recent_batches = Batch.objects.filter(firm=profile.firm).order_by("-created_at")[:10]
    context = {
        "active_nav": "intake",
        "profile": profile,
        "ay": current_assessment_year(),
        "recent_batches": recent_batches,
    }
    return render(request, "portal/intake.html", context)


@portal_view
def batch_detail(request, profile, pk):
    batch = get_object_or_404(Batch, pk=pk, firm=profile.firm)
    documents = batch.documents.select_related("client", "doc_code").order_by("id")
    context = {"active_nav": "intake", "profile": profile, "batch": batch, "documents": documents}
    return render(request, "portal/batch_detail.html", context)


@portal_view
def reminders_view(request, profile):
    firm = profile.firm

    if request.method == "POST":
        action = request.POST.get("action")
        client_ids = request.POST.getlist("client_ids")
        selected = Client.objects.filter(firm=firm, pk__in=client_ids)
        if action == "send_initial":
            for c in selected:
                send_initial_request(c)
            messages.success(request, f"Sent initial request to {selected.count()} client(s).")
        elif action == "send_followup":
            sent = sum(1 for c in selected if send_followup(c))
            messages.success(request, f"Sent follow-up to {sent} client(s) (Ready clients skipped).")
        return redirect("portal:reminders")

    clients = Client.objects.filter(firm=firm).order_by("name")
    rows = [(c, compute_itr_status(c)) for c in clients]
    logs = ReminderLog.objects.filter(firm=firm).select_related("client").order_by("-sent_at")[:30]
    context = {"active_nav": "reminders", "profile": profile, "rows": rows, "logs": logs}
    return render(request, "portal/reminders.html", context)


@firm_admin_required
def settings_view(request, profile):
    firm = profile.firm
    categories = Category.objects.filter(firm=firm).prefetch_related("doc_codes").order_by("name")
    doc_codes = DocCode.objects.filter(firm=firm).order_by("code")
    context = {"active_nav": "settings", "profile": profile, "categories": categories, "doc_codes": doc_codes}
    return render(request, "portal/settings.html", context)

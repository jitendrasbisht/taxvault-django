import math
from collections import Counter
from datetime import timedelta
from pathlib import Path

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django_q.tasks import async_task

from django.db import connection, transaction
from django.db.models import Count

from clients.forms import ManualClientAddForm
from clients.imports import import_clients_from_file
from clients.models import Category, Client, DocCode, ReminderLog
from clients.reminders import send_followup, send_initial_request
from clients.services import ClientDataError, update_client, upsert_client
from documents.models import Batch, Document
from documents.storage import absolute_path
from documents.services import ReviewResolutionError, resolve_review_document
from documents.status import compute_itr_status
from taxvault.ay import current_assessment_year, next_filing_deadline
from taxvault.vault_naming import vault_folder_path

from .auth import firm_admin_required, portal_view


def _radar_chart(rows, size=220, rings=(0.25, 0.5, 0.75, 1.0)):
    """SVG geometry for the bottleneck radar (Section 18 addendum) -- computed server-side,
    same approach already used for the status donut, so the template just draws points."""
    n = len(rows)
    cx = cy = size / 2
    max_r = size * 0.34
    label_r = max_r * 1.22

    def point(i, frac):
        angle = math.radians(-90 + i * (360 / n))
        return cx + max_r * frac * math.cos(angle), cy + max_r * frac * math.sin(angle)

    grid_rings = []
    for frac in rings:
        pts = [point(i, frac) for i in range(n)]
        grid_rings.append(" ".join(f"{x:.1f},{y:.1f}" for x, y in pts))

    axes = []
    for i, row in enumerate(rows):
        x2, y2 = point(i, 1.0)
        lx, ly = point(i, label_r / max_r)
        axes.append({"x1": cx, "y1": cy, "x2": x2, "y2": y2, "label_x": lx, "label_y": ly, "label": row["code"]})

    data_pts = [point(i, row["pct"] / 100) for i, row in enumerate(rows)]
    data_polygon = " ".join(f"{x:.1f},{y:.1f}" for x, y in data_pts)
    data_dots = [{"x": round(x, 1), "y": round(y, 1)} for x, y in data_pts]

    return {
        "size": size, "grid_rings": grid_rings, "axes": axes,
        "data_polygon": data_polygon, "data_dots": data_dots,
    }


@portal_view
def dashboard(request, profile):
    """Section 18 addendum: firm-level analytics summary, separate from the Clients table.
    Every number here is computed live from real Client/Document/ReminderLog data — nothing
    hardcoded. The one thing deliberately NOT built: per-email open/click tracking (Section
    11 still excludes that) — the reminder funnel stops at 'became Ready', not 'opened'."""
    firm = profile.firm
    ay = current_assessment_year()
    clients = list(Client.objects.filter(firm=firm).prefetch_related("categories"))

    statuses = []
    counts = {"ready": 0, "in_progress": 0, "not_started": 0}
    for client in clients:
        status = compute_itr_status(client, ay=ay)
        counts[status.status] += 1
        statuses.append((client, status))

    total_clients = len(clients)
    ready_pct = round(100 * counts["ready"] / total_clients) if total_clients else 0

    today = timezone.localdate()
    week_start = today - timedelta(days=6)
    filed_this_week_qs = Document.objects.filter(
        firm=firm, status=Document.STATUS_FILED, filed_at__date__gte=week_start
    )
    docs_filed_this_week = filed_this_week_qs.count()
    daily_counts = [filed_this_week_qs.filter(filed_at__date=week_start + timedelta(days=i)).count() for i in range(7)]
    max_daily = max(daily_counts) or 1
    spark_points = [
        f"{i * (100 / 6):.1f},{20 - (c / max_daily) * 18:.1f}" for i, c in enumerate(daily_counts)
    ]
    spark_polyline = " ".join(spark_points)

    review_count = Document.objects.filter(firm=firm, review_reason__isnull=False).count()

    bottleneck = Counter()
    for _client, status in statuses:
        for code in status.missing_codes:
            bottleneck[code] += 1
    bottleneck_ranked = sorted(bottleneck.items(), key=lambda kv: -kv[1])[:8]
    max_bottleneck = bottleneck_ranked[0][1] if bottleneck_ranked else 1
    bottleneck_rows = [
        {"code": code, "count": count, "pct": round(100 * count / max_bottleneck)}
        for code, count in bottleneck_ranked
    ]
    bottleneck_radar = _radar_chart(bottleneck_rows, size=170) if len(bottleneck_rows) >= 3 else None

    ranked = []
    for client, status in statuses:
        total = len(status.required_codes)
        if not total:
            continue
        pct = round(100 * len(status.received_codes & status.required_codes) / total)
        ranked.append((pct, client, status))
    ranked.sort(key=lambda t: t[0])
    worst = ranked[:11]
    heat_codes = sorted({code for _, _, status in worst for code in status.required_codes})
    heat_rows = []
    for pct, client, status in worst:
        cells = []
        for code in heat_codes:
            if code not in status.required_codes:
                cells.append({"code": code, "state": "na"})
            elif code in status.received_codes:
                cells.append({"code": code, "state": "recv"})
            else:
                cells.append({"code": code, "state": "miss"})
        heat_rows.append({"client": client, "pct": pct, "cells": cells, "ready": status.status == "ready"})
    heat_footer = []
    for code in heat_codes:
        required_n = sum(1 for _, _, s in worst if code in s.required_codes)
        recv_n = sum(1 for _, _, s in worst if code in s.received_codes)
        heat_footer.append({"code": code, "pct": round(100 * recv_n / required_n) if required_n else 0})

    category_mix = list(
        Category.objects.filter(firm=firm)
        .annotate(client_count=Count("clients", distinct=True))
        .order_by("-client_count")
    )
    max_cat = category_mix[0].client_count if category_mix and category_mix[0].client_count else 1

    activity = []
    for d in (
        Document.objects.filter(firm=firm, status=Document.STATUS_FILED, filed_at__isnull=False)
        .select_related("client", "doc_code").order_by("-filed_at")[:8]
    ):
        client_name = d.client.name if d.client else "an unmatched client"
        doc_label = d.doc_code.code if d.doc_code else "A document"
        activity.append({"ts": d.filed_at, "text": f"{doc_label} filed for {client_name}"})
    for r in ReminderLog.objects.filter(firm=firm).select_related("client").order_by("-sent_at")[:8]:
        activity.append({"ts": r.sent_at, "text": f"{r.get_stage_display()} sent to {r.client.name}"})
    for c in Client.objects.filter(firm=firm).order_by("-created_at")[:8]:
        activity.append({"ts": c.created_at, "text": f"New client added — {c.name}"})
    activity.sort(key=lambda a: a["ts"], reverse=True)
    activity = activity[:5]

    month_start = today.replace(day=1)
    stage1_sent = ReminderLog.objects.filter(
        firm=firm, stage=ReminderLog.STAGE_INITIAL, sent_at__date__gte=month_start
    ).count()
    stage2_sent = ReminderLog.objects.filter(
        firm=firm, stage=ReminderLog.STAGE_FOLLOWUP, sent_at__date__gte=month_start
    ).count()
    reminded_ids = set(
        ReminderLog.objects.filter(firm=firm, sent_at__date__gte=month_start).values_list("client_id", flat=True)
    )
    now_ready = sum(1 for client, status in statuses if client.id in reminded_ids and status.status == "ready")
    funnel_max = max(stage1_sent, 1)
    stage1_pct = round(100 * stage1_sent / funnel_max)
    stage2_pct = round(100 * stage2_sent / funnel_max)
    now_ready_pct = round(100 * now_ready / funnel_max)

    in_progress_pct = round(100 * counts["in_progress"] / total_clients) if total_clients else 0
    not_started_pct = round(100 * counts["not_started"] / total_clients) if total_clients else 0
    donut_segments = [
        {"pct": ready_pct, "remainder": 100 - ready_pct, "offset": 0, "color": "#10b981"},
        {"pct": in_progress_pct, "remainder": 100 - in_progress_pct, "offset": -ready_pct, "color": "#f59e0b"},
        {
            "pct": not_started_pct, "remainder": 100 - not_started_pct,
            "offset": -(ready_pct + in_progress_pct), "color": "#f43f5e",
        },
    ]

    leaderboard = list(
        ReminderLog.objects.filter(firm=firm, sent_at__date__gte=month_start, sent_by__isnull=False)
        .values("sent_by__username")
        .annotate(n=Count("id"))
        .order_by("-n")[:5]
    )

    deadline = next_filing_deadline()
    days_left = (deadline - today).days
    ring_circumference = 106.8
    ring_fraction = min(max(days_left / 365, 0), 1)
    deadline_ring_dasharray = f"{ring_fraction * ring_circumference:.1f} {ring_circumference}"

    context = {
        "active_nav": "dashboard",
        "profile": profile,
        "ay": ay,
        "total_clients": total_clients,
        "counts": counts,
        "ready_pct": ready_pct,
        "docs_filed_this_week": docs_filed_this_week,
        "spark_polyline": spark_polyline,
        "review_count": review_count,
        "bottleneck_rows": bottleneck_rows,
        "bottleneck_radar": bottleneck_radar,
        "heat_codes": heat_codes,
        "heat_rows": heat_rows,
        "heat_footer": heat_footer,
        "category_mix": category_mix,
        "max_cat": max_cat,
        "activity": activity,
        "stage1_sent": stage1_sent,
        "stage2_sent": stage2_sent,
        "now_ready": now_ready,
        "stage1_pct": stage1_pct,
        "stage2_pct": stage2_pct,
        "now_ready_pct": now_ready_pct,
        "donut_segments": donut_segments,
        "leaderboard": leaderboard,
        "deadline": deadline,
        "days_left": days_left,
        "deadline_ring_dasharray": deadline_ring_dasharray,
    }
    return render(request, "portal/dashboard.html", context)


@portal_view
def clients_list(request, profile):
    """The searchable/editable Client Master table — split out from the analytics Dashboard
    (Section 18 addendum) so the two pages stop looking like duplicates of each other."""
    firm = profile.firm
    clients = Client.objects.filter(firm=firm).select_related("last_edited_by").order_by("name")

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
        "active_nav": "clients",
        "profile": profile,
        "ay": current_assessment_year(),
        "rows": rows,
        "counts": counts,
        "total_clients": clients.count(),
        "query": query,
        "status_filter": status_filter,
    }
    return render(request, "portal/clients_list.html", context)


@portal_view
def import_clients_view(request, profile):
    """Section 2 bulk import, self-service via the portal (no script/terminal needed).
    PAN is the match key (Section 3's top identity signal) — existing PANs for this firm
    are updated in place, new PANs are created, matching upsert_client's own behavior."""
    result = None
    if request.method == "POST" and request.FILES.get("file"):
        upload = request.FILES["file"]
        result = import_clients_from_file(profile.firm, upload, upload.name, edited_by=request.user)
        if result.created or result.updated:
            messages.success(
                request,
                f"Import complete — {result.created} new client(s) added, "
                f"{result.updated} already existed and were updated.",
            )
        if result.errors:
            messages.error(request, f"{len(result.errors)} row(s) could not be imported — see details below.")

    context = {"active_nav": "clients", "profile": profile, "result": result}
    return render(request, "portal/import_clients.html", context)


@portal_view
def delete_clients_view(request, profile):
    """Targeted delete (one or several, picked via checkboxes on the Dashboard) — separate
    from Settings' firm-wide 'Clear All Clients' reset, and open to Staff too (Section 14:
    Staff has full Clients access, same as manual add)."""
    firm = profile.firm
    client_ids = request.POST.getlist("client_ids")
    if not client_ids:
        messages.error(request, "No clients selected.")
        return redirect("portal:clients_list")

    clients = Client.objects.filter(firm=firm, pk__in=client_ids)

    if request.POST.get("confirm") == "yes":
        delete_documents = request.POST.get("delete_documents") == "on"
        with transaction.atomic():
            docs = Document.objects.filter(firm=firm, client__in=clients)
            linked_doc_count = docs.count()
            if delete_documents:
                for doc in docs:
                    for p in (doc.storage_path, doc.archive_path):
                        if p:
                            fp = absolute_path(p)
                            if fp.exists():
                                fp.unlink()
                docs.delete()
            deleted_count = clients.count()
            clients.delete()
        msg = f"Deleted {deleted_count} client(s)."
        if delete_documents and linked_doc_count:
            msg += f" Also deleted {linked_doc_count} linked document(s)."
        messages.success(request, msg)
        return redirect("portal:clients_list")

    linked_doc_count = Document.objects.filter(firm=firm, client__in=clients).count()
    context = {
        "active_nav": "clients",
        "profile": profile,
        "clients": clients,
        "client_ids": client_ids,
        "linked_doc_count": linked_doc_count,
    }
    return render(request, "portal/delete_clients_confirm.html", context)


@portal_view
def manual_add_client_view(request, profile):
    """Section 2 manual individual add, in the portal (same form/service the admin's
    manual-add view uses — one logic path via upsert_client, not two)."""
    if request.method == "POST":
        form = ManualClientAddForm(request.POST, locked_firm=profile.firm)
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
                verb = "Added" if created else "Updated"
                messages.success(request, f"{verb} client {client.pan} — {client.name}.")
                return redirect("portal:clients_list")
    else:
        form = ManualClientAddForm(locked_firm=profile.firm)

    context = {"active_nav": "clients", "profile": profile, "form": form}
    return render(request, "portal/manual_add_client.html", context)


@firm_admin_required
def edit_client_view(request, profile, pk):
    """Edit an existing client's own details (PAN, name, phone, email, aadhar, categories)
    without touching the database directly. Firm Admin only, per explicit instruction --
    Staff keep add/view/delete but not edit. Uses update_client (keyed by pk), not
    upsert_client (keyed by PAN) -- changing the PAN here must rename this row, not create
    a second one."""
    client = get_object_or_404(Client, pk=pk, firm=profile.firm)

    if request.method == "POST":
        form = ManualClientAddForm(request.POST, locked_firm=profile.firm)
        if form.is_valid():
            cd = form.cleaned_data
            category_names = [c.name for c in cd["categories"]]
            try:
                update_client(
                    client, cd["pan"], cd["name"], cd["phone"], cd["email"], cd["aadhar"], category_names,
                    edited_by=request.user,
                )
            except ClientDataError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, f"Updated client {client.pan} — {client.name}.")
                return redirect("portal:client_detail", pk=client.pk)
    else:
        form = ManualClientAddForm(
            locked_firm=profile.firm,
            initial={
                "pan": client.pan,
                "name": client.name,
                "phone": client.phone,
                "email": client.email,
                "categories": client.categories.all(),
            },
        )

    context = {"active_nav": "clients", "profile": profile, "form": form, "client": client}
    return render(request, "portal/edit_client.html", context)


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
            send_initial_request(client, sent_by=request.user)
            messages.success(request, f"Sent initial request to {client.name}.")
        elif action == "send_followup":
            if send_followup(client, sent_by=request.user):
                messages.success(request, f"Sent follow-up to {client.name}.")
            else:
                messages.info(request, f"{client.name} is already Ready — no follow-up sent.")
        return redirect("portal:client_detail", pk=pk)

    context = {
        "active_nav": "clients",
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
                send_initial_request(c, sent_by=request.user)
            messages.success(request, f"Sent initial request to {selected.count()} client(s).")
        elif action == "send_followup":
            sent = sum(1 for c in selected if send_followup(c, sent_by=request.user))
            messages.success(request, f"Sent follow-up to {sent} client(s) (Ready clients skipped).")
        return redirect("portal:reminders")

    clients = Client.objects.filter(firm=firm).order_by("name")
    rows = [(c, compute_itr_status(c)) for c in clients]
    logs = ReminderLog.objects.filter(firm=firm).select_related("client").order_by("-sent_at")[:30]
    context = {"active_nav": "reminders", "profile": profile, "rows": rows, "logs": logs}
    return render(request, "portal/reminders.html", context)


@firm_admin_required
def clear_all_clients_view(request, profile):
    """Self-service 'start fresh' reset — Firm Admin only, since it's irreversible and
    firm-wide. Requires an explicit confirm step; shows counts up front so nothing is a
    surprise, including documents that would be orphaned (client set to null) unless the
    admin also opts to delete those."""
    firm = profile.firm
    client_count = Client.objects.filter(firm=firm).count()
    reminder_count = ReminderLog.objects.filter(firm=firm).count()
    linked_doc_count = Document.objects.filter(firm=firm, client__isnull=False).count()

    if request.method == "POST" and request.POST.get("confirm") == "yes":
        delete_documents = request.POST.get("delete_documents") == "on"
        with transaction.atomic():
            if delete_documents:
                docs = Document.objects.filter(firm=firm, client__isnull=False)
                for doc in docs:
                    for p in (doc.storage_path, doc.archive_path):
                        if p:
                            fp = absolute_path(p)
                            if fp.exists():
                                fp.unlink()
                docs.delete()
            Client.objects.filter(firm=firm).delete()
        messages.success(
            request,
            f"Cleared {client_count} client(s) and {reminder_count} reminder log(s)"
            + (f", and deleted {linked_doc_count} linked document(s)." if delete_documents else "."),
        )
        return redirect("portal:clients_list")

    context = {
        "active_nav": "settings",
        "profile": profile,
        "client_count": client_count,
        "reminder_count": reminder_count,
        "linked_doc_count": linked_doc_count,
    }
    return render(request, "portal/clear_all_clients.html", context)


def _reset_serial_sequence(model):
    """Restarts a table's auto-increment counter at 1 — only called once the table is
    globally empty (see clear_all_batches_view), since these tables are shared across
    firms (Section 13) and resetting while another firm still has rows would risk a
    primary-key collision on their next insert."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_get_serial_sequence(%s, 'id')", [model._meta.db_table])
        seq_name = cursor.fetchone()[0]
        if seq_name:
            cursor.execute(f"ALTER SEQUENCE {seq_name} RESTART WITH 1")


@firm_admin_required
def clear_all_batches_view(request, profile):
    """Self-service reset for Document Intake history — deletes every Batch (and its
    Documents/files) for this firm. Batch/Document ids are a single global sequence shared
    by every firm, not one per firm, so numbering only restarts at #1 when doing so is
    globally safe (no other firm has any rows left in these tables)."""
    firm = profile.firm
    batch_count = Batch.objects.filter(firm=firm).count()
    doc_count = Document.objects.filter(firm=firm).count()

    if request.method == "POST" and request.POST.get("confirm") == "yes":
        with transaction.atomic():
            docs = Document.objects.filter(firm=firm)
            for doc in docs:
                for p in (doc.storage_path, doc.archive_path):
                    if p:
                        fp = absolute_path(p)
                        if fp.exists():
                            fp.unlink()
            docs.delete()
            Batch.objects.filter(firm=firm).delete()

            sequence_reset = False
            if not Batch.objects.exists() and not Document.objects.exists():
                _reset_serial_sequence(Batch)
                _reset_serial_sequence(Document)
                sequence_reset = True

        msg = f"Cleared {batch_count} batch(es) and {doc_count} document(s)."
        msg += " Batch numbering restarted from #1." if sequence_reset else (
            " Numbering wasn't restarted — another firm still has batch/document records "
            "in the shared table."
        )
        messages.success(request, msg)
        return redirect("portal:intake")

    context = {
        "active_nav": "intake",
        "profile": profile,
        "batch_count": batch_count,
        "doc_count": doc_count,
    }
    return render(request, "portal/clear_all_batches.html", context)


@firm_admin_required
def settings_view(request, profile):
    firm = profile.firm
    categories = Category.objects.filter(firm=firm).prefetch_related("doc_codes").order_by("name")
    doc_codes = DocCode.objects.filter(firm=firm).order_by("code")
    context = {"active_nav": "settings", "profile": profile, "categories": categories, "doc_codes": doc_codes}
    return render(request, "portal/settings.html", context)


@portal_view
def about_view(request, profile):
    context = {"active_nav": "about", "profile": profile}
    return render(request, "portal/about.html", context)

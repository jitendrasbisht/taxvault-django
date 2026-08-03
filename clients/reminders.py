"""Section 11: manual, two-stage, email-only reminders. Every function here is only ever
called from an explicit staff-triggered admin action -- no schedule, no signal, no automated
send of any kind."""

from django.conf import settings
from django.core.mail import send_mail

from .models import DocCode, ReminderLog

# documents depends on clients, never the reverse for models -- but this module is only
# ever imported from clients/admin.py (after all apps' models are ready), same as the
# cross-app import already used there for ITR status.
from documents.status import compute_itr_status


def _doc_code_display_names(firm, codes):
    lookup = {dc.code: dc.display_name for dc in DocCode.objects.filter(firm=firm, code__in=codes)}
    return sorted(lookup.get(code, code) for code in codes)


def send_initial_request(client, sent_by=None):
    """Stage 1: one individually-addressed email listing the client's full Required Docs
    list (friendly names), regardless of what's already been received."""
    names = _doc_code_display_names(client.firm, client.required_doc_codes().values_list("code", flat=True))
    subject = f"Document Request — {client.name}"
    body = (
        f"Dear {client.name},\n\n"
        "To proceed with your ITR filing, please share the following documents:\n\n"
        + "\n".join(f"- {n}" for n in names)
        + "\n\nThank you.\n"
    )
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [client.email])
    ReminderLog.objects.create(
        firm=client.firm, client=client, stage=ReminderLog.STAGE_INITIAL, subject=subject, body=body,
        sent_by=sent_by,
    )


def send_followup(client, sent_by=None):
    """Stage 2: recalculates Required - Received at send time and lists only what's still
    missing. Returns False (no email sent, no log entry) if the client is already Ready."""
    status = compute_itr_status(client)
    if status.status == "ready":
        return False

    names = _doc_code_display_names(client.firm, status.missing_codes)
    subject = f"Reminder: Documents Still Pending — {client.name}"
    body = (
        f"Dear {client.name},\n\n"
        "This is a follow-up reminder. The following documents are still pending:\n\n"
        + "\n".join(f"- {n}" for n in names)
        + "\n\nThank you.\n"
    )
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [client.email])
    ReminderLog.objects.create(
        firm=client.firm, client=client, stage=ReminderLog.STAGE_FOLLOWUP, subject=subject, body=body,
        sent_by=sent_by,
    )
    return True

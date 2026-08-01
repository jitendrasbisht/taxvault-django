"""Ready for ITR status (Section 9). Lives in documents, not clients, so the one-way
dependency the rest of this app follows (documents -> clients, never the reverse) holds
here too — this needs both Client (Required Docs) and Document (Received Docs)."""

from dataclasses import dataclass

from taxvault.ay import current_assessment_year

from .models import Document

STATUS_READY = "ready"
STATUS_IN_PROGRESS = "in_progress"
STATUS_NOT_STARTED = "not_started"


@dataclass(frozen=True)
class ITRStatus:
    ay: str
    required_codes: frozenset
    received_codes: frozenset
    missing_codes: frozenset
    status: str
    label: str


def compute_itr_status(client, ay=None) -> ITRStatus:
    """
    Required Docs = Base + union of DocCodes from tagged categories (Section 5).
    Received Docs = all non-MISC, classified documents filed under the client for the AY.
    Missing = Required - Received. MISC never counts until manually reclassified.
    """
    ay = ay or current_assessment_year()

    required_codes = frozenset(client.required_doc_codes().values_list("code", flat=True))
    received_codes = frozenset(
        Document.objects.filter(client=client, ay=ay, status=Document.STATUS_FILED)
        .exclude(doc_code__code="MISC")
        .values_list("doc_code__code", flat=True)
    )
    missing_codes = required_codes - received_codes
    received_required_count = len(required_codes & received_codes)
    total = len(required_codes)

    if not missing_codes:
        status, label = STATUS_READY, "Ready"
    elif received_required_count == 0:
        status, label = STATUS_NOT_STARTED, "Not Started"
    else:
        status, label = STATUS_IN_PROGRESS, f"In Progress ({received_required_count} of {total} received)"

    return ITRStatus(
        ay=ay, required_codes=required_codes, received_codes=received_codes,
        missing_codes=missing_codes, status=status, label=label,
    )

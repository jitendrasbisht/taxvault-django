"""Section 10 resolution: once staff assigns a client and/or DocCode, the document is
immediately renamed and moved into the vault — the same outcome as an automatic match,
just human-confirmed. It never stays behind in the Review Queue or exists in two places."""

from django.utils import timezone

from taxvault.vault_naming import vault_filename, vault_folder_path

from .models import Document
from .storage import copy_from_review_pending_to_vault, move_within_vault


class ReviewResolutionError(Exception):
    pass


def resolve_review_document(document, client, doc_code):
    if client is None:
        raise ReviewResolutionError("A client must be assigned.")
    if doc_code is None:
        raise ReviewResolutionError("A DocCode must be assigned.")
    if client.firm_id != document.firm_id or doc_code.firm_id != document.firm_id:
        raise ReviewResolutionError("Client and DocCode must belong to the same firm as the document.")

    today = timezone.localdate()
    ext = document.original_filename.rsplit(".", 1)[-1] if "." in document.original_filename else ""
    vault_relative = vault_folder_path(client.pan, client.name, document.ay) + vault_filename(
        client.pan, doc_code.code, document.ay, today, ext
    )

    if document.status == Document.STATUS_REVIEW:
        # Currently sitting in Review_Pending -- that location becomes the archived original.
        new_vault_path = copy_from_review_pending_to_vault(document.storage_path, vault_relative)
        document.archive_path = document.storage_path
    else:
        # Already filed as MISC -- move the existing vault file to its corrected name/location.
        new_vault_path = move_within_vault(document.storage_path, vault_relative)

    document.client = client
    document.doc_code = doc_code
    document.storage_path = new_vault_path
    document.status = Document.STATUS_FILED
    document.review_reason = None
    document.is_possible_duplicate = False
    document.filed_at = timezone.now()
    document.save()
    return document

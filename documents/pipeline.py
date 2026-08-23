"""Core intake pipeline (Section 4), built and verified as a plain synchronous function
first (per explicit sequencing choice) before being wrapped in a Django-Q task."""

from pathlib import Path

from django.utils import timezone

from taxvault.vault_naming import vault_filename, vault_folder_path

from .classification import classify, compute_content_hash, find_exact_duplicate, find_possible_duplicate
from .extraction import (
    IMAGE_EXTENSIONS,
    PDF_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    detect_identifiers,
    extract_text,
    looks_like_scanned_pdf,
    match_client,
)
from .models import Document
from .storage import file_and_archive, move_to_review_pending


def _mask_aadhar(digits):
    return f"XXXX-XXXX-{digits[-4:]}" if digits else None


def _display_value(candidates, is_matched_type, matched_value):
    """For the informational detected_* fields on Document: show the value that actually
    matched, or the first candidate found if nothing matched (still useful for a human
    reviewing the Review Queue to see what was in the document)."""
    if is_matched_type:
        return matched_value
    return candidates[0] if candidates else None


def process_batch(batch):
    """Processes every file currently in batch.folder_path. Safe to call once per batch —
    files are relocated out of the watched folder as they're handled, so nothing is
    reprocessed on a later run."""
    folder = Path(batch.folder_path)
    firm = batch.firm
    today = timezone.localdate()

    for src_path in sorted(p for p in folder.iterdir() if p.is_file()):
        batch.files_found += 1
        ext = src_path.suffix.lower()
        original_filename = src_path.name

        if ext not in SUPPORTED_EXTENSIONS:
            # Section 4: skip/flag non-document file types, don't attempt to process them.
            batch.files_skipped += 1
            continue

        content_hash = compute_content_hash(src_path)
        if find_exact_duplicate(firm, content_hash):
            # Section 8: skip exact duplicate re-processing entirely.
            batch.files_skipped += 1
            src_path.unlink()
            continue

        if ext in IMAGE_EXTENSIONS:
            # OCR is deferred (no GCP Vision credentials yet) -- the honest equivalent of
            # "no identifier found," not a guess.
            review_path = move_to_review_pending(src_path, batch.id, original_filename)
            Document.objects.create(
                batch=batch, firm=firm, ay=batch.ay,
                original_filename=original_filename, content_hash=content_hash,
                extraction_method=Document.EXTRACTION_NONE,
                status=Document.STATUS_REVIEW,
                review_reason="OCR not available yet for scanned/image files.",
                storage_path=review_path,
            )
            batch.files_review += 1
            continue

        try:
            text = extract_text(src_path)
        except Exception:
            # A malformed/corrupted/incomplete file (more likely now that files can arrive
            # via browser upload, not just a locally-verified folder) shouldn't take down
            # the rest of the batch -- one unreadable file is exactly what Review Queue is
            # for, same as the "OCR not available" case just above.
            review_path = move_to_review_pending(src_path, batch.id, original_filename)
            Document.objects.create(
                batch=batch, firm=firm, ay=batch.ay,
                original_filename=original_filename, content_hash=content_hash,
                extraction_method=Document.EXTRACTION_NONE,
                status=Document.STATUS_REVIEW,
                review_reason="Could not read this file — it may be corrupted or not a valid file of its type.",
                storage_path=review_path,
            )
            batch.files_review += 1
            continue

        identifiers = detect_identifiers(text)
        client, match_method, matched_value = match_client(firm, identifiers)

        detected_pan = _display_value(identifiers["pans"], match_method == "pan", matched_value)
        detected_aadhar_digits = _display_value(
            identifiers["aadhar_digits_list"], match_method == "aadhar", matched_value
        )
        detected_aadhar_masked = _mask_aadhar(detected_aadhar_digits)
        detected_account = _display_value(identifiers["accounts"], match_method == "account", matched_value)
        detected_phone = _display_value(identifiers["phones"], match_method == "phone", matched_value)

        possible_dup = find_possible_duplicate(firm, detected_pan, original_filename) if detected_pan else None

        if client is None:
            review_path = move_to_review_pending(src_path, batch.id, original_filename)
            if looks_like_scanned_pdf(text) and ext in PDF_EXTENSIONS:
                reason = "This looks like a scanned PDF with no readable text — OCR not available yet."
            elif looks_like_scanned_pdf(text):
                reason = "This file has little to no readable content."
            elif not any(identifiers.values()):
                reason = "No PAN/Aadhar/Account Number/Phone detected in the document."
            else:
                reason = "Detected identifier did not match any client."
            Document.objects.create(
                batch=batch, firm=firm, ay=batch.ay,
                original_filename=original_filename, content_hash=content_hash,
                extraction_method=Document.EXTRACTION_TEXT,
                detected_pan=detected_pan, detected_aadhar_masked=detected_aadhar_masked,
                detected_account=detected_account, detected_phone=detected_phone, match_method=match_method,
                status=Document.STATUS_REVIEW, review_reason=reason,
                storage_path=review_path,
                is_possible_duplicate=bool(possible_dup), duplicate_of=possible_dup,
            )
            batch.files_review += 1
            continue

        if possible_dup:
            # Matched fine, but Section 8 says flag for manual review rather than silently
            # skip or overwrite -- hold it instead of auto-filing.
            review_path = move_to_review_pending(src_path, batch.id, original_filename)
            Document.objects.create(
                batch=batch, firm=firm, client=client, ay=batch.ay,
                original_filename=original_filename, content_hash=content_hash,
                extraction_method=Document.EXTRACTION_TEXT,
                detected_pan=detected_pan, detected_aadhar_masked=detected_aadhar_masked,
                detected_account=detected_account, detected_phone=detected_phone, match_method=match_method,
                status=Document.STATUS_REVIEW,
                review_reason=f"Possible duplicate of '{possible_dup.original_filename}' (same PAN, similar filename).",
                storage_path=review_path,
                is_possible_duplicate=True, duplicate_of=possible_dup,
            )
            batch.files_review += 1
            continue

        doc_code = classify(firm, text)
        is_misc = doc_code.code == "MISC"

        vault_relative = vault_folder_path(client.pan, client.name, batch.ay) + vault_filename(
            client.pan, doc_code.code, batch.ay, today, ext
        )
        vault_path, archive_path = file_and_archive(src_path, vault_relative, batch.id, original_filename)

        Document.objects.create(
            batch=batch, firm=firm, client=client, doc_code=doc_code, ay=batch.ay,
            original_filename=original_filename, content_hash=content_hash,
            extraction_method=Document.EXTRACTION_TEXT,
            detected_pan=detected_pan, detected_aadhar_masked=detected_aadhar_masked,
            detected_account=detected_account, detected_phone=detected_phone, match_method=match_method,
            status=Document.STATUS_FILED,
            review_reason="Unclassified — filed as MISC, needs manual reclassification." if is_misc else None,
            storage_path=vault_path, archive_path=archive_path,
            filed_at=timezone.now(),
        )
        batch.files_filed += 1

    batch.completed_at = timezone.now()
    batch.save()

"""Keyword-based classification (Section 6) and duplicate detection (Section 8). No
ML/LLM classification, no fuzzy matching — a document either matches a configured keyword
or it doesn't, and falls to MISC."""

import hashlib
import re
from pathlib import Path

from clients.models import DocCode

from .models import Document


def compute_content_hash(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify(firm, text: str):
    """Returns the matching DocCode, or the firm's MISC DocCode if no keyword matches.
    is_base (Section 5: required for every client) is a separate concept from whether a
    DocCode is a valid classification target — AIS and 26AS are still classifiable."""
    text_lower = text.lower()
    for doc_code in DocCode.objects.filter(firm=firm).exclude(code="MISC").order_by("code"):
        for keyword in doc_code.keywords:
            if keyword.strip() and keyword.strip().lower() in text_lower:
                return doc_code
    return DocCode.objects.get(firm=firm, code="MISC")


def _normalize_filename_stem(filename: str) -> str:
    """Loose normalization so "statement (1).pdf" and "statement_copy.pdf" both collapse
    toward "statement" for the same-PAN-similar-filename duplicate check (Section 8)."""
    stem = Path(filename).stem.lower()
    stem = re.sub(r"[\s_-]*\(?\d+\)?$", "", stem)
    stem = re.sub(r"[\s_-]*copy$", "", stem)
    stem = re.sub(r"[^a-z0-9]", "", stem)
    return stem


def find_exact_duplicate(firm, content_hash: str):
    """Section 8: skip exact duplicate re-processing entirely (by file content hash)."""
    return Document.objects.filter(firm=firm, content_hash=content_hash).first()


def find_possible_duplicate(firm, pan: str, original_filename: str):
    """Section 8: same-PAN + similar-filename is flagged for manual review, not silently
    skipped or overwritten — this is deliberately looser than the exact-hash check."""
    if not pan:
        return None
    target_stem = _normalize_filename_stem(original_filename)
    if not target_stem:
        return None
    for doc in Document.objects.filter(firm=firm, detected_pan=pan):
        if _normalize_filename_stem(doc.original_filename) == target_stem:
            return doc
    return None

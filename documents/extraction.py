"""Text extraction (Section 4) and identity matching (Section 3). Text-based PDFs only for
now — OCR for scanned/image files is deferred until Google Cloud Vision credentials are
available; those files are routed to Review Queue instead of guessed at."""

import re

from pypdf import PdfReader

from clients.models import AADHAR_DIGITS_REGEX, PAN_REGEX, Client, hash_aadhar_digits

_AADHAR_TEXT_RE = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
_PHONE_TEXT_RE = re.compile(r"(?:\+91[-\s]?|0)?([6-9]\d{9})\b")
_PAN_TEXT_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")

TEXT_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | IMAGE_EXTENSIONS

# Mirrors documents.models.Document.MATCH_* — kept as plain strings here so this module
# doesn't have to import documents.models (one-way dependency: documents imports clients,
# never the other way).
MATCH_PAN = "pan"
MATCH_AADHAR = "aadhar"
MATCH_PHONE = "phone"
MATCH_NONE = "none"


def extract_text_from_pdf(path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def detect_identifiers(text: str) -> dict:
    """Returns whichever identifiers are found in the text — first match of each kind,
    not exhaustive. Priority order is applied later, at match time (Section 3)."""
    pan_match = _PAN_TEXT_RE.search(text)
    aadhar_match = _AADHAR_TEXT_RE.search(text)
    phone_match = _PHONE_TEXT_RE.search(text)

    aadhar_digits = None
    if aadhar_match:
        digits = re.sub(r"\D", "", aadhar_match.group())
        if AADHAR_DIGITS_REGEX.match(digits):
            aadhar_digits = digits

    return {
        "pan": pan_match.group() if pan_match else None,
        "aadhar_digits": aadhar_digits,
        "phone": phone_match.group(1) if phone_match else None,
    }


def match_client(firm, identifiers: dict):
    """Priority: PAN, then Aadhar, then Phone (Section 3). No name matching, no fuzzy
    matching — an unresolved identifier means Review Queue, never a guess."""
    pan = identifiers.get("pan")
    if pan and PAN_REGEX.match(pan):
        client = Client.objects.filter(firm=firm, pan=pan).first()
        if client:
            return client, MATCH_PAN

    aadhar_digits = identifiers.get("aadhar_digits")
    if aadhar_digits:
        client = Client.objects.filter(firm=firm, aadhar_hash=hash_aadhar_digits(aadhar_digits)).first()
        if client:
            return client, MATCH_AADHAR

    phone = identifiers.get("phone")
    if phone:
        client = Client.objects.filter(firm=firm, phone__endswith=phone[-10:]).first()
        if client:
            return client, MATCH_PHONE

    return None, MATCH_NONE

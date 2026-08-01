"""Text extraction (Section 4) and identity matching (Section 3). Text-based PDFs only for
now — OCR for scanned/image files is deferred until Google Cloud Vision credentials are
available; those files are routed to Review Queue instead of guessed at."""

import re

from pypdf import PdfReader

from clients.models import AADHAR_DIGITS_REGEX, PAN_REGEX, Client, hash_aadhar_digits

_AADHAR_TEXT_RE = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
# (?<!\d)/(?!\d) instead of \b on the leading edge: a plain \b would still let this match
# start in the middle of a longer digit run (e.g. a bank account number), since \b only
# checks a word/non-word transition and digits are all "word" characters to regex.
_PHONE_TEXT_RE = re.compile(r"(?<!\d)(?:\+91[-\s]?|0)?([6-9]\d{9})(?!\d)")
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
    """Returns every PAN/Aadhar/phone-shaped match found in the text, in order of
    appearance -- not just the first. Real documents like Form 16 legitimately contain more
    than one PAN (the deductor's and the employee's), so match_client has to check each
    exact candidate against the Client Master rather than assume the first one found is the
    client's."""
    pans = list(dict.fromkeys(_PAN_TEXT_RE.findall(text)))

    aadhar_digits_list = []
    for raw in _AADHAR_TEXT_RE.findall(text):
        digits = re.sub(r"\D", "", raw)
        if AADHAR_DIGITS_REGEX.match(digits) and digits not in aadhar_digits_list:
            aadhar_digits_list.append(digits)

    phones = list(dict.fromkeys(m for m in _PHONE_TEXT_RE.findall(text)))

    return {"pans": pans, "aadhar_digits_list": aadhar_digits_list, "phones": phones}


def match_client(firm, identifiers: dict):
    """Priority: PAN, then Aadhar, then Phone (Section 3). Every exact candidate of the
    higher-priority type is checked before falling back to the next type. Still no name
    matching, no fuzzy matching — an unresolved identifier means Review Queue, never a
    guess. Returns (client_or_None, match_method, matched_value_or_None)."""
    for pan in identifiers.get("pans", []):
        if PAN_REGEX.match(pan):
            client = Client.objects.filter(firm=firm, pan=pan).first()
            if client:
                return client, MATCH_PAN, pan

    for digits in identifiers.get("aadhar_digits_list", []):
        client = Client.objects.filter(firm=firm, aadhar_hash=hash_aadhar_digits(digits)).first()
        if client:
            return client, MATCH_AADHAR, digits

    for phone in identifiers.get("phones", []):
        client = Client.objects.filter(firm=firm, phone__endswith=phone[-10:]).first()
        if client:
            return client, MATCH_PHONE, phone

    return None, MATCH_NONE, None

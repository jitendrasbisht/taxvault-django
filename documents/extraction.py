"""Text extraction (Section 4) and identity matching (Section 3). Text-based PDFs and
spreadsheets (Section 4 addendum: bank/MF statements increasingly arrive as Excel/CSV
exports, not PDFs) for now — OCR for scanned/image files is deferred until Google Cloud
Vision credentials are available; those files are routed to Review Queue instead of
guessed at."""

import csv
import re
from pathlib import Path

import openpyxl
from pypdf import PdfReader

from clients.models import AADHAR_DIGITS_REGEX, PAN_REGEX, Client, hash_aadhar_digits

_AADHAR_TEXT_RE = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
# (?<!\d)/(?!\d) instead of \b on the leading edge: a plain \b would still let this match
# start in the middle of a longer digit run (e.g. a bank account number), since \b only
# checks a word/non-word transition and digits are all "word" characters to regex.
_PHONE_TEXT_RE = re.compile(r"(?<!\d)(?:\+91[-\s]?|0)?([6-9]\d{9})(?!\d)")
_PAN_TEXT_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
# Bank account numbers have no fixed format/checksum (unlike PAN/Aadhar), so a bare
# 9-18 digit run is far too prone to false positives on a bank statement -- transaction
# refs, cheque numbers, IFSC-adjacent digits, etc. are all the same shape. Anchoring to a
# nearby "a/c no" / "account number" label (Section 3's own reasoning for treating Phone as
# the weakest signal) keeps this from being an even weaker one. "no"/"number" is required
# (not optional) so an unrelated label like "Account Type" can't anchor a match. The window
# after the label is generous (up to 300 chars, not just adjacent) because a PDF table's
# "Account Number" column header commonly gets flattened well ahead of the actual value
# cell once extracted as plain text -- real statements have shown a 100+ char gap.
_ACCOUNT_TEXT_RE = re.compile(
    r"(?:a/?c(?:count)?|acct)\.?\s*(?:no\.?|number)[\s\S]{0,300}?(?<!\d)(\d{9,18})(?!\d)",
    re.IGNORECASE,
)

PDF_EXTENSIONS = {".pdf"}
# Legacy .xls (pre-2007 binary format) is deliberately not included -- reading it would
# need a new dependency (xlrd) beyond openpyxl, which the rest of the app already uses for
# client bulk-import. Real-world bank/broker exports are overwhelmingly .xlsx or .csv today.
SPREADSHEET_EXTENSIONS = {".xlsx", ".csv"}
TEXT_EXTENSIONS = PDF_EXTENSIONS | SPREADSHEET_EXTENSIONS
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | IMAGE_EXTENSIONS

# A scanned/photographed page saved as .pdf has no real text layer -- pypdf returns little
# to nothing for it (sometimes a handful of stray characters from artifacts, rarely truly
# zero), unlike a genuine digital PDF which always has a meaningful amount of text.
MIN_MEANINGFUL_TEXT_LENGTH = 20


def looks_like_scanned_pdf(text: str) -> bool:
    return len(text.strip()) < MIN_MEANINGFUL_TEXT_LENGTH

# Mirrors documents.models.Document.MATCH_* — kept as plain strings here so this module
# doesn't have to import documents.models (one-way dependency: documents imports clients,
# never the other way).
MATCH_PAN = "pan"
MATCH_AADHAR = "aadhar"
MATCH_ACCOUNT = "account"
MATCH_PHONE = "phone"
MATCH_NONE = "none"


def extract_text_from_pdf(path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_text_from_spreadsheet(path) -> str:
    """Flattens every cell (all sheets, for .xlsx) into one text blob, so the exact same
    keyword/identifier detection built for PDFs (detect_identifiers, classify) works
    unchanged and extension-agnostic -- an account number or a doc-code keyword reads the
    same whether it came from a PDF paragraph or a spreadsheet cell."""
    suffix = Path(path).suffix.lower()
    lines = []
    if suffix == ".csv":
        with open(path, newline="", encoding="utf-8-sig", errors="ignore") as f:
            for row in csv.reader(f):
                lines.append(" ".join(str(cell) for cell in row if cell))
    else:
        # openpyxl's read-only mode keeps the file handle open (streams rows lazily) until
        # explicitly closed -- on Windows that leaves it locked, so the pipeline's later
        # shutil.move() into the vault fails with a "file in use" error unless this is
        # closed the moment reading is done, not left for garbage collection.
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        try:
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    lines.append(" ".join(str(cell) for cell in row if cell is not None))
        finally:
            wb.close()
    return "\n".join(lines)


def extract_text(path) -> str:
    """Single entry point the pipeline calls regardless of file type -- dispatches to the
    right extractor by extension. Keeps pipeline.py from needing to know the difference."""
    if Path(path).suffix.lower() in SPREADSHEET_EXTENSIONS:
        return extract_text_from_spreadsheet(path)
    return extract_text_from_pdf(path)


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
    accounts = list(dict.fromkeys(_ACCOUNT_TEXT_RE.findall(text)))

    return {
        "pans": pans, "aadhar_digits_list": aadhar_digits_list,
        "accounts": accounts, "phones": phones,
    }


def match_client(firm, identifiers: dict):
    """Priority: PAN, then Aadhar, then Account Number, then Phone (Section 3, extended by
    the Section 19 addendum). Every exact candidate of the higher-priority type is checked
    before falling back to the next type. Still no name matching, no fuzzy matching — an
    unresolved identifier means Review Queue, never a guess. Returns (client_or_None,
    match_method, matched_value_or_None)."""
    for pan in identifiers.get("pans", []):
        if PAN_REGEX.match(pan):
            client = Client.objects.filter(firm=firm, pan=pan).first()
            if client:
                return client, MATCH_PAN, pan

    for digits in identifiers.get("aadhar_digits_list", []):
        client = Client.objects.filter(firm=firm, aadhar_hash=hash_aadhar_digits(digits)).first()
        if client:
            return client, MATCH_AADHAR, digits

    if identifiers.get("accounts"):
        # account_number can hold a comma-separated list (a client may have more than one
        # bank account) -- exact-match the field itself, then confirm precisely against the
        # parsed list, so "1234" can't accidentally match inside a longer stored number.
        candidates = Client.objects.filter(firm=firm).exclude(account_number="").exclude(account_number__isnull=True)
        for account in identifiers["accounts"]:
            client = next((c for c in candidates if account in c.account_number_list()), None)
            if client:
                return client, MATCH_ACCOUNT, account

    for phone in identifiers.get("phones", []):
        client = Client.objects.filter(firm=firm, phone__endswith=phone[-10:]).first()
        if client:
            return client, MATCH_PHONE, phone

    return None, MATCH_NONE, None

"""Bulk client import (Section 2) — Excel/CSV, writing into the same Client Master table
used by manual add. No automatic client creation logic beyond what's in this file — an
unresolvable row is reported as an error, never guessed."""

import csv
import io
from dataclasses import dataclass, field

import openpyxl
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import PAN_REGEX, Category, Client

REQUIRED_HEADERS = {"pan", "name", "phone"}
HEADER_ALIASES = {
    "pan": "pan",
    "client name": "name",
    "name": "name",
    "phone": "phone",
    "aadhar": "aadhar",
    "aadhaar": "aadhar",
    "category tags": "categories",
    "category": "categories",
    "categories": "categories",
}


@dataclass
class ImportError:
    row: int
    reason: str


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    errors: list = field(default_factory=list)


def _normalize_headers(raw_headers):
    normalized = []
    for h in raw_headers:
        key = (h or "").strip().lower()
        normalized.append(HEADER_ALIASES.get(key))
    return normalized


def _read_rows(file_obj, filename):
    """Yields (row_number, dict) for each data row. row_number starts at 2 (row 1 = header)."""
    if filename.lower().endswith(".csv"):
        text = io.TextIOWrapper(file_obj, encoding="utf-8-sig")
        reader = csv.reader(text)
        rows = list(reader)
    elif filename.lower().endswith((".xlsx", ".xlsm")):
        wb = openpyxl.load_workbook(file_obj, read_only=True, data_only=True)
        ws = wb.active
        rows = [[cell if cell is not None else "" for cell in row] for row in ws.iter_rows(values_only=True)]
    else:
        raise ValueError("Unsupported file type — only .csv and .xlsx are accepted.")

    if not rows:
        return

    headers = _normalize_headers(rows[0])
    if not REQUIRED_HEADERS.issubset({h for h in headers if h}):
        missing = REQUIRED_HEADERS - {h for h in headers if h}
        raise ValueError(f"Missing required column(s): {', '.join(sorted(missing))}")

    for i, raw_row in enumerate(rows[1:], start=2):
        row = {}
        for header, value in zip(headers, raw_row):
            if header:
                row[header] = str(value).strip() if value is not None else ""
        if any(row.values()):
            yield i, row


def import_clients_from_file(firm, file_obj, filename):
    """Parses file_obj (binary file-like) and upserts into Client Master, scoped to firm."""
    result = ImportResult()
    firm_categories = {c.name.strip().lower(): c for c in Category.objects.filter(firm=firm)}

    try:
        rows = list(_read_rows(file_obj, filename))
    except ValueError as exc:
        result.errors.append(ImportError(row=0, reason=str(exc)))
        return result

    for row_num, row in rows:
        pan = row.get("pan", "").strip().upper()
        name = row.get("name", "").strip()
        phone = row.get("phone", "").strip()
        aadhar = row.get("aadhar", "").strip()
        category_names = [c.strip() for c in row.get("categories", "").split(",") if c.strip()]

        if not pan or not name or not phone:
            result.errors.append(ImportError(row=row_num, reason="PAN, Client Name, and Phone are required."))
            continue

        if not PAN_REGEX.match(pan):
            result.errors.append(ImportError(row=row_num, reason=f"Invalid PAN format: {pan}"))
            continue

        categories = []
        unknown = []
        for cname in category_names:
            cat = firm_categories.get(cname.lower())
            if cat:
                categories.append(cat)
            else:
                unknown.append(cname)
        if unknown:
            result.errors.append(
                ImportError(row=row_num, reason=f"Unknown category tag(s) for this firm: {', '.join(unknown)}")
            )
            continue

        try:
            with transaction.atomic():
                existing = Client.objects.filter(firm=firm, pan=pan).first()
                client = existing or Client(firm=firm, pan=pan)
                client.name = name
                client.phone = phone
                if aadhar:
                    client.set_aadhar(aadhar)
                client.full_clean(exclude=["aadhar_hash", "aadhar_masked", "categories"])
                client.save()
                client.categories.set(categories)
        except ValidationError as exc:
            reason = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            result.errors.append(ImportError(row=row_num, reason=reason))
            continue

        if existing:
            result.updated += 1
        else:
            result.created += 1

    return result

"""Bulk client import (Section 2) — Excel/CSV. Row parsing only; the actual create/update
logic lives in services.upsert_client, shared with manual add so there is one logic path,
not two, writing into the Client Master table."""

import csv
import io
from dataclasses import dataclass, field

import openpyxl

from .services import ClientDataError, upsert_client

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

    try:
        rows = list(_read_rows(file_obj, filename))
    except ValueError as exc:
        result.errors.append(ImportError(row=0, reason=str(exc)))
        return result

    for row_num, row in rows:
        category_names = [c.strip() for c in row.get("categories", "").split(",") if c.strip()]

        try:
            _client, created = upsert_client(
                firm,
                row.get("pan", ""),
                row.get("name", ""),
                row.get("phone", ""),
                row.get("aadhar", ""),
                category_names,
            )
        except ClientDataError as exc:
            result.errors.append(ImportError(row=row_num, reason=str(exc)))
            continue

        if created:
            result.created += 1
        else:
            result.updated += 1

    return result

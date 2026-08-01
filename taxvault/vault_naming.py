"""Vault naming convention (Section 8) — pure string-building functions only. No file I/O
and no storage backend here: Section 4 (document intake) and the Cloudflare R2 decision
(Section 17) are both still deferred, so nothing in this module touches an actual file."""

import re

_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|]')


def short_ay_label(ay_label: str) -> str:
    """"2026-27" (from taxvault.ay.current_assessment_year()) -> "AY26-27", the short form
    used in Section 8's folder/filename examples."""
    start, end = ay_label.split("-")
    return f"AY{start[-2:]}-{end}"


def _sanitize_client_name(name: str) -> str:
    """Strips whitespace (Section 8's example: "Priya Mehta" -> "PriyaMehta") and
    filesystem-unsafe characters, since this becomes part of a folder path."""
    return _UNSAFE_CHARS.sub("", re.sub(r"\s+", "", name))


def vault_folder_path(pan: str, client_name: str, ay_label: str) -> str:
    """/Vault/{PAN}_{ClientName}/{AY}/ (Section 8)."""
    return f"/Vault/{pan}_{_sanitize_client_name(client_name)}/{short_ay_label(ay_label)}/"


def vault_filename(pan: str, doc_code: str, ay_label: str, processed_date, extension: str) -> str:
    """{PAN}_{DocCode}_{AY}_{Date}.ext, Date = file processed date as YYMMDD (Section 8)."""
    ext = extension.lstrip(".")
    date_str = processed_date.strftime("%y%m%d")
    return f"{pan}_{doc_code}_{short_ay_label(ay_label)}_{date_str}.{ext}"

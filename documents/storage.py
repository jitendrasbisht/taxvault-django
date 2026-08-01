"""Local filesystem stand-in for Cloudflare R2 (Section 17, deferred until credentials are
provided). Resolves the pure path strings from taxvault.vault_naming against VAULT_ROOT and
performs the actual move/archive file operations. Swapping to R2 later means replacing the
handful of functions in this module with S3-compatible calls — nothing else in the pipeline
should need to change."""

import shutil
from pathlib import Path

from django.conf import settings


def _resolve(relative_path: str) -> Path:
    """"/Vault/PAN_Name/AY26-27/file.pdf" -> VAULT_ROOT/Vault/PAN_Name/AY26-27/file.pdf."""
    return Path(settings.VAULT_ROOT) / relative_path.lstrip("/\\")


def _unique_destination(relative_path: str) -> str:
    """Never silently overwrite (Section 8): if the target filename is already taken,
    append a numeric suffix."""
    dest = _resolve(relative_path)
    if not dest.exists():
        return relative_path
    stem, suffix = dest.stem, dest.suffix
    parent_relative = relative_path.rsplit("/", 1)[0]
    n = 2
    while True:
        candidate_relative = f"{parent_relative}/{stem}_{n}{suffix}"
        if not _resolve(candidate_relative).exists():
            return candidate_relative
        n += 1


def file_and_archive(src_path: Path, vault_relative_path: str, batch_id: int, original_filename: str):
    """Section 8: rename+move into the vault happens as one step at time of filing, and the
    original is separately archived, never deleted — so the source file has to end up in two
    places. Copies into the vault first (if that fails, the source is untouched), then
    relocates the original into Processed_Archive. Returns (vault_relative, archive_relative)."""
    vault_final = _unique_destination(vault_relative_path)
    vault_dest = _resolve(vault_final)
    vault_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src_path), str(vault_dest))

    archive_relative = f"/Processed_Archive/batch_{batch_id}/{original_filename}"
    archive_final = _unique_destination(archive_relative)
    archive_dest = _resolve(archive_final)
    archive_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src_path), str(archive_dest))

    return vault_final, archive_final


def move_to_review_pending(src_path: Path, batch_id: int, original_filename: str) -> str:
    """Section 10: an unmatched document goes to Review Queue unmodified/unrenamed — this
    just relocates it out of the watched folder so a re-scan won't reprocess it."""
    relative_path = f"/Review_Pending/batch_{batch_id}/{original_filename}"
    final_relative = _unique_destination(relative_path)
    dest = _resolve(final_relative)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src_path), str(dest))
    return final_relative


def copy_from_review_pending_to_vault(review_relative_path: str, vault_relative_path: str) -> str:
    """Resolution step (Section 10): the Review_Pending file becomes the archived original
    in place, and a copy is filed into the vault under its now-known name."""
    src = _resolve(review_relative_path)
    final_relative = _unique_destination(vault_relative_path)
    dest = _resolve(final_relative)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dest))
    return final_relative


def move_within_vault(old_relative_path: str, new_relative_path: str) -> str:
    """Resolution step (Section 10): a MISC document gets manually reclassified, so its
    vault filename (which embeds the DocCode) has to change too."""
    src = _resolve(old_relative_path)
    final_relative = _unique_destination(new_relative_path)
    dest = _resolve(final_relative)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return final_relative

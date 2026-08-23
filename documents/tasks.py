"""Django-Q wrapper around the already-verified synchronous pipeline (Section 17:
background jobs for batch folder intake). No new logic lives here — process_batch() is
the single source of truth, called identically by run_intake_batch and this task."""

import shutil
from pathlib import Path

from django.conf import settings

from .models import Batch
from .pipeline import process_batch


def run_batch(batch_id: int):
    batch = Batch.objects.get(id=batch_id)
    process_batch(batch)

    # A browser-uploaded batch (Section 4 addendum) stages its source files under
    # VAULT_ROOT/Uploads/ instead of a user-owned folder -- unlike a folder-path batch,
    # that staging directory belongs to the app, so it's safe to remove entirely once
    # processing is done, including any skipped/unsupported files process_batch
    # deliberately leaves untouched in the source folder.
    uploads_root = Path(settings.VAULT_ROOT) / "Uploads"
    folder = Path(batch.folder_path)
    if folder == uploads_root or uploads_root in folder.parents:
        shutil.rmtree(folder, ignore_errors=True)

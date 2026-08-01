"""Django-Q wrapper around the already-verified synchronous pipeline (Section 17:
background jobs for batch folder intake). No new logic lives here — process_batch() is
the single source of truth, called identically by run_intake_batch and this task."""

from .models import Batch
from .pipeline import process_batch


def run_batch(batch_id: int):
    batch = Batch.objects.get(id=batch_id)
    process_batch(batch)

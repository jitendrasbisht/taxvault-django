from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from clients.models import Firm
from documents.models import Batch
from documents.pipeline import process_batch
from taxvault.ay import current_assessment_year


class Command(BaseCommand):
    help = "Run one folder-intake batch (Section 4) synchronously — verification step before Django-Q wiring."

    def add_arguments(self, parser):
        parser.add_argument("firm_id", type=int)
        parser.add_argument("folder_path", type=str)
        parser.add_argument("--ay", type=str, default=None, help="Override the computed current AY, e.g. 2026-27")

    def handle(self, *args, **options):
        try:
            firm = Firm.objects.get(id=options["firm_id"])
        except Firm.DoesNotExist:
            raise CommandError(f"No firm with id={options['firm_id']}")

        folder = Path(options["folder_path"])
        if not folder.is_dir():
            raise CommandError(f"Not a directory: {folder}")

        ay = options["ay"] or current_assessment_year()

        batch = Batch.objects.create(firm=firm, ay=ay, folder_path=str(folder))
        process_batch(batch)
        batch.refresh_from_db()

        self.stdout.write(self.style.SUCCESS(
            f"Batch #{batch.id} — found: {batch.files_found}  filed: {batch.files_filed}  "
            f"review: {batch.files_review}  skipped: {batch.files_skipped}"
        ))
        for doc in batch.documents.filter(review_reason__isnull=False).order_by("id"):
            self.stdout.write(self.style.WARNING(f"  [{doc.original_filename}] {doc.review_reason}"))

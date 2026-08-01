from django.core.management.base import BaseCommand, CommandError

from clients.imports import import_clients_from_file
from clients.models import Firm


class Command(BaseCommand):
    help = "Bulk import clients from a CSV or Excel file into the Client Master table (Section 2)."

    def add_arguments(self, parser):
        parser.add_argument("firm_id", type=int)
        parser.add_argument("file_path", type=str)

    def handle(self, *args, **options):
        try:
            firm = Firm.objects.get(id=options["firm_id"])
        except Firm.DoesNotExist:
            raise CommandError(f"No firm with id={options['firm_id']}")

        file_path = options["file_path"]
        with open(file_path, "rb") as f:
            result = import_clients_from_file(firm, f, file_path)

        self.stdout.write(self.style.SUCCESS(f"Created: {result.created}  Updated: {result.updated}  Errors: {len(result.errors)}"))
        for err in result.errors:
            self.stdout.write(self.style.WARNING(f"  Row {err.row}: {err.reason}"))

from django.core.management.base import BaseCommand

from clients.models import Category, Firm

# Section 5's locked category list — seeded as a starting point for a new firm's
# configurable Category table. Section 13: new firms are added manually by the admin.
DEFAULT_CATEGORIES = [
    "Salaried",
    "Stock/Equity Investor",
    "Mutual Fund Investor",
    "Home Loan Borrower",
    "Rental Income",
    "Donations (80G)",
    "Insurance (80C/80D)",
    "NPS Contributor",
    "Business/Professional Income",
]


class Command(BaseCommand):
    help = "Manually create a new firm (Section 13) and seed it with the default category list (Section 5)."

    def add_arguments(self, parser):
        parser.add_argument("name", type=str, help="Firm name")

    def handle(self, *args, **options):
        firm = Firm.objects.create(name=options["name"])
        for cname in DEFAULT_CATEGORIES:
            Category.objects.create(firm=firm, name=cname)
        self.stdout.write(self.style.SUCCESS(f"Created firm '{firm.name}' (id={firm.id}) with {len(DEFAULT_CATEGORIES)} default categories."))

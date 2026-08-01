from django.core.management.base import BaseCommand

from clients.models import Category, DocCode, Firm

# Section 6's locked DocCode table — (code, display_name, is_base). Keywords are left
# blank; not specified in the locked spec, left for the firm to configure later.
DOC_CODES = [
    ("Form16", "Form 16 (Salary TDS Certificate)", False),
    ("Form16A", "Form 16A (Non-salary TDS Certificate)", False),
    ("AIS", "AIS (Annual Information Statement)", True),
    ("TIS", "TIS (Taxpayer Information Summary)", False),
    ("26AS", "26AS", True),
    ("CGSTMT", "Capital Gains Statement", False),
    ("MFSTMT", "Mutual Fund Statement", False),
    ("BANKSTMT", "Bank Statement", False),
    ("BANKINT", "Bank Interest Certificate", False),
    ("80C", "80C Investment Proof", False),
    ("80D", "80D (Health Insurance Premium)", False),
    ("80G", "80G (Donation Receipt)", False),
    ("HLINT", "Home Loan Interest Certificate", False),
    ("RENT", "Rent Receipt", False),
    ("RENTAGR", "Rent Agreement", False),
    ("PAYSLIP", "Salary Slip", False),
    ("AADHAR", "Aadhar Card", False),
    ("PANCARD", "PAN Card", False),
    ("DEMAT", "Demat/Broker Statement", False),
    ("NPS", "NPS Statement", False),
    ("PROPDEED", "Property Sale Deed", False),
    ("MISC", "Unclassified / no keyword match", False),
]

# Section 5's locked Category -> DocCode requirement mapping.
CATEGORY_DOC_CODES = {
    "Salaried": ["Form16"],
    "Stock/Equity Investor": ["CGSTMT", "DEMAT"],
    "Mutual Fund Investor": ["MFSTMT"],
    "Home Loan Borrower": ["HLINT"],
    "Rental Income": ["RENT", "RENTAGR"],
    "Donations (80G)": ["80G"],
    "Insurance (80C/80D)": ["80C", "80D"],
    "NPS Contributor": ["NPS"],
    "Business/Professional Income": ["BANKSTMT"],
}


class Command(BaseCommand):
    help = (
        "Manually create a new firm (Section 13) and seed it with the locked default "
        "category list (Section 5), DocCode table (Section 6), and Category->DocCode "
        "requirement mapping (Section 5)."
    )

    def add_arguments(self, parser):
        parser.add_argument("name", type=str, help="Firm name")

    def handle(self, *args, **options):
        firm = Firm.objects.create(name=options["name"])

        doc_codes_by_code = {}
        for code, display_name, is_base in DOC_CODES:
            doc_codes_by_code[code] = DocCode.objects.create(
                firm=firm, code=code, display_name=display_name, is_base=is_base
            )

        for cname, codes in CATEGORY_DOC_CODES.items():
            category = Category.objects.create(firm=firm, name=cname)
            category.doc_codes.set([doc_codes_by_code[c] for c in codes])

        self.stdout.write(
            self.style.SUCCESS(
                f"Created firm '{firm.name}' (id={firm.id}) with {len(DOC_CODES)} DocCodes "
                f"and {len(CATEGORY_DOC_CODES)} categories."
            )
        )

import hashlib
import re

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")
AADHAR_DIGITS_REGEX = re.compile(r"^\d{12}$")

pan_validator = RegexValidator(
    regex=PAN_REGEX,
    message="PAN must match the format AAAAA9999A (5 letters, 4 digits, 1 letter).",
)


def hash_aadhar_digits(digits: str) -> str:
    """The one hashing implementation for Aadhar (Section 3) — used both when a client's
    Aadhar is entered and when matching a detected Aadhar number from a document."""
    return hashlib.sha256(digits.encode()).hexdigest()


class Firm(models.Model):
    """A CA firm — the multi-tenancy boundary (Section 13). Created manually by the system admin."""

    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    """Section 14: exactly two roles, each user scoped to exactly one firm (no per-client
    staff assignment — a Staff or Firm Admin user sees all of their firm's clients)."""

    ROLE_FIRM_ADMIN = "firm_admin"
    ROLE_STAFF = "staff"
    ROLE_CHOICES = [
        (ROLE_FIRM_ADMIN, "Firm Admin"),
        (ROLE_STAFF, "Staff"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    firm = models.ForeignKey(Firm, on_delete=models.CASCADE, related_name="members")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)

    def __str__(self):
        return f"{self.user.username} — {self.get_role_display()} @ {self.firm.name}"


class DocCode(models.Model):
    """Configurable, per-firm DocCode table (Section 6): code, friendly display name, and the
    keywords used for keyword-based classification. is_base marks the Section 5 base documents
    (AIS, 26AS) required for every client regardless of category."""

    firm = models.ForeignKey(Firm, on_delete=models.CASCADE, related_name="doc_codes")
    code = models.CharField(max_length=20)
    display_name = models.CharField(max_length=255)
    keywords = ArrayField(models.CharField(max_length=100), default=list, blank=True)
    is_base = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["firm", "code"], name="unique_doccode_per_firm"),
        ]

    def __str__(self):
        return self.code


class Category(models.Model):
    """Configurable, per-firm category tag (Section 5 / Section 13). Not a fixed choices field."""

    firm = models.ForeignKey(Firm, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=100)
    doc_codes = models.ManyToManyField(DocCode, related_name="categories", blank=True)

    class Meta:
        verbose_name_plural = "categories"
        constraints = [
            models.UniqueConstraint(fields=["firm", "name"], name="unique_category_per_firm"),
        ]

    def __str__(self):
        return self.name


class Client(models.Model):
    """Client Master (Section 2). Single table for both bulk-import and manual-add onboarding paths."""

    firm = models.ForeignKey(Firm, on_delete=models.CASCADE, related_name="clients")

    pan = models.CharField(max_length=10, validators=[pan_validator])
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20)
    # Not in Section 2's original field list, but Section 11 (Reminders) requires an
    # individually-addressed email per client and has no other source for one -- added
    # with explicit approval as a gap-fill, same required-ness as Phone.
    email = models.EmailField(max_length=254, blank=True, default="")

    # Aadhar is optional and, per Section 3, stored masked/hashed — never plaintext.
    aadhar_hash = models.CharField(max_length=64, null=True, blank=True, editable=False)
    aadhar_masked = models.CharField(max_length=14, null=True, blank=True, editable=False)

    categories = models.ManyToManyField(Category, related_name="clients", blank=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["firm", "pan"], name="unique_pan_per_firm"),
        ]

    def __str__(self):
        return f"{self.pan} — {self.name}"

    def clean(self):
        if self.pan:
            self.pan = self.pan.upper()
            if not PAN_REGEX.match(self.pan):
                raise ValidationError({"pan": "PAN must match the format AAAAA9999A."})

    def set_aadhar(self, raw_aadhar):
        """Hash + mask a raw 12-digit Aadhar number. Raw value is never persisted."""
        if not raw_aadhar:
            self.aadhar_hash = None
            self.aadhar_masked = None
            return
        digits = re.sub(r"\D", "", raw_aadhar)
        if not AADHAR_DIGITS_REGEX.match(digits):
            raise ValidationError({"aadhar": "Aadhar must be exactly 12 digits."})
        self.aadhar_hash = hash_aadhar_digits(digits)
        self.aadhar_masked = f"XXXX-XXXX-{digits[-4:]}"

    def required_doc_codes(self):
        """Required Docs = Base + union of DocCodes from tagged categories (Section 5)."""
        base = DocCode.objects.filter(firm=self.firm, is_base=True)
        from_categories = DocCode.objects.filter(categories__in=self.categories.all())
        return (base | from_categories).distinct()


class ReminderLog(models.Model):
    """Section 11: simple send log (client, stage, date sent) -- visibility into reminder
    history so staff can see what's already gone out. Created only by an actual send, never
    manually."""

    STAGE_INITIAL = "initial"
    STAGE_FOLLOWUP = "followup"
    STAGE_CHOICES = [
        (STAGE_INITIAL, "Initial Request"),
        (STAGE_FOLLOWUP, "Follow-up"),
    ]

    firm = models.ForeignKey(Firm, on_delete=models.CASCADE, related_name="reminder_logs")
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="reminder_logs")
    stage = models.CharField(max_length=10, choices=STAGE_CHOICES)
    sent_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.client.pan} — {self.get_stage_display()} — {self.sent_at:%Y-%m-%d}"

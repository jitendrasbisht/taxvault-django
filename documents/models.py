from django.conf import settings
from django.db import models

from clients.models import Client, DocCode, Firm


class Batch(models.Model):
    """One folder-intake run (Section 4). Section 7: the AY is selected once per batch,
    pre-filled with the computed current AY but overridable, and every document processed
    in the run inherits it."""

    firm = models.ForeignKey(Firm, on_delete=models.CASCADE, related_name="batches")
    ay = models.CharField(max_length=10)
    folder_path = models.CharField(max_length=1000)
    triggered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    files_found = models.IntegerField(default=0)
    files_filed = models.IntegerField(default=0)
    files_review = models.IntegerField(default=0)
    files_skipped = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "batches"

    def __str__(self):
        return f"Batch #{self.pk} — {self.firm.name} — AY {self.ay}"


class Document(models.Model):
    """A single intake file's full lifecycle (Section 4/6/8/10). Review Queue membership
    and filed state are NOT separate tables — Section 10 is explicit that a resolved
    review-queue item becomes the filed record, not a second row alongside it."""

    STATUS_REVIEW = "review"
    STATUS_FILED = "filed"
    STATUS_CHOICES = [
        (STATUS_REVIEW, "Needs Review"),
        (STATUS_FILED, "Filed"),
    ]

    MATCH_PAN = "pan"
    MATCH_AADHAR = "aadhar"
    MATCH_PHONE = "phone"
    MATCH_NONE = "none"
    MATCH_CHOICES = [
        (MATCH_PAN, "PAN"),
        (MATCH_AADHAR, "Aadhar"),
        (MATCH_PHONE, "Phone"),
        (MATCH_NONE, "No match"),
    ]

    EXTRACTION_TEXT = "text"
    EXTRACTION_OCR = "ocr"
    EXTRACTION_NONE = "none"
    EXTRACTION_CHOICES = [
        (EXTRACTION_TEXT, "Text"),
        (EXTRACTION_OCR, "OCR"),
        (EXTRACTION_NONE, "None"),
    ]

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="documents")
    firm = models.ForeignKey(Firm, on_delete=models.CASCADE, related_name="documents")
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents")
    doc_code = models.ForeignKey(DocCode, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents")
    ay = models.CharField(max_length=10)

    original_filename = models.CharField(max_length=500)
    content_hash = models.CharField(max_length=64, db_index=True)
    extraction_method = models.CharField(max_length=10, choices=EXTRACTION_CHOICES, default=EXTRACTION_NONE)

    detected_pan = models.CharField(max_length=10, null=True, blank=True)
    detected_aadhar_masked = models.CharField(max_length=14, null=True, blank=True)
    detected_phone = models.CharField(max_length=20, null=True, blank=True)
    match_method = models.CharField(max_length=10, choices=MATCH_CHOICES, default=MATCH_NONE)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_REVIEW)
    review_reason = models.CharField(max_length=500, null=True, blank=True)

    storage_path = models.CharField(max_length=1000)
    archive_path = models.CharField(max_length=1000, null=True, blank=True)

    is_possible_duplicate = models.BooleanField(default=False)
    duplicate_of = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="duplicates")

    filed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.original_filename} ({self.get_status_display()})"

    def in_review_queue(self):
        """Section 10: unmatched docs AND matched-but-MISC docs both show in the queue —
        the second case stays 'filed' while also needing manual reclassification."""
        return bool(self.review_reason)

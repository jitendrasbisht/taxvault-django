from django import forms

from .models import Category, Firm


class ManualClientAddForm(forms.Form):
    """Same fields as bulk import (Section 2): PAN, Client Name, Phone, Aadhar (optional),
    Category tags. A plain Form, not a ModelForm, since Aadhar is write-only (hashed/masked
    on save, never a real model field) and category choices must be validated against firm."""

    firm = forms.ModelChoiceField(queryset=Firm.objects.all())
    pan = forms.CharField(max_length=10, label="PAN")
    name = forms.CharField(max_length=255, label="Client Name")
    phone = forms.CharField(max_length=20)
    aadhar = forms.CharField(
        max_length=14, required=False, label="Aadhar (optional)",
        help_text="Never stored in plaintext — only a masked value and a hash are kept.",
    )
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.none(), widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Category.objects.select_related("firm").order_by("firm__name", "name")
        self.fields["categories"].queryset = qs
        self.fields["categories"].label_from_instance = lambda c: f"{c.firm.name} — {c.name}"

    def clean(self):
        cleaned = super().clean()
        firm = cleaned.get("firm")
        categories = cleaned.get("categories")
        if firm and categories:
            mismatched = [c.name for c in categories if c.firm_id != firm.id]
            if mismatched:
                raise forms.ValidationError(
                    f"These categories don't belong to {firm.name}: {', '.join(mismatched)}"
                )
        return cleaned

from django import forms

from .models import Category, Firm, UserProfile


class ManualClientAddForm(forms.Form):
    """Same fields as bulk import (Section 2): PAN, Client Name, Phone, Aadhar (optional),
    Category tags. A plain Form, not a ModelForm, since Aadhar is write-only (hashed/masked
    on save, never a real model field) and category choices must be validated against firm.

    When `locked_firm` is passed (a Firm Admin / Staff user, per Section 14), the firm field
    is removed entirely and categories are restricted to that firm — Section 13 isolation.
    A superuser (no locked_firm) still gets the open firm picker, for internal admin use."""

    _INPUT_CSS = (
        "w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none "
        "focus:border-slate-300 focus:bg-white"
    )

    firm = forms.ModelChoiceField(queryset=Firm.objects.all(), required=False)
    pan = forms.CharField(
        max_length=10, label="PAN", widget=forms.TextInput(attrs={"class": _INPUT_CSS})
    )
    name = forms.CharField(
        max_length=255, label="Client Name", widget=forms.TextInput(attrs={"class": _INPUT_CSS})
    )
    phone = forms.CharField(max_length=20, widget=forms.TextInput(attrs={"class": _INPUT_CSS}))
    email = forms.EmailField(max_length=254, widget=forms.EmailInput(attrs={"class": _INPUT_CSS}))
    aadhar = forms.CharField(
        max_length=14, required=False, label="Aadhar (optional)",
        help_text="Never stored in plaintext — only a masked value and a hash are kept.",
        widget=forms.TextInput(attrs={"class": _INPUT_CSS}),
    )
    account_number = forms.CharField(
        max_length=255, required=False, label="Bank Account Number(s) (optional)",
        help_text="Used to match incoming statements/certificates. Separate multiple accounts with a comma.",
        widget=forms.TextInput(attrs={"class": _INPUT_CSS}),
    )
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.none(), widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, locked_firm=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.locked_firm = locked_firm
        if locked_firm:
            del self.fields["firm"]
            self.fields["categories"].queryset = Category.objects.filter(firm=locked_firm).order_by("name")
        else:
            self.fields["categories"].queryset = Category.objects.select_related("firm").order_by(
                "firm__name", "name"
            )
            self.fields["categories"].label_from_instance = lambda c: f"{c.firm.name} — {c.name}"

    def clean(self):
        cleaned = super().clean()
        firm = self.locked_firm or cleaned.get("firm")
        if not firm:
            raise forms.ValidationError("Firm is required.")
        cleaned["firm"] = firm

        categories = cleaned.get("categories")
        if categories:
            mismatched = [c.name for c in categories if c.firm_id != firm.id]
            if mismatched:
                raise forms.ValidationError(
                    f"These categories don't belong to {firm.name}: {', '.join(mismatched)}"
                )
        return cleaned


class FirmUserAddForm(forms.Form):
    """Section 14 staff management. When `locked_firm` is passed (a Firm Admin, not a
    superuser), the firm field is removed and the new login is always scoped to that firm."""

    firm = forms.ModelChoiceField(queryset=Firm.objects.all(), required=False)
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput, min_length=8)
    role = forms.ChoiceField(choices=UserProfile.ROLE_CHOICES)

    def __init__(self, *args, locked_firm=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.locked_firm = locked_firm
        if locked_firm:
            del self.fields["firm"]

    def clean(self):
        cleaned = super().clean()
        firm = self.locked_firm or cleaned.get("firm")
        if not firm:
            raise forms.ValidationError("Firm is required.")
        cleaned["firm"] = firm
        return cleaned


class ResetPasswordForm(forms.Form):
    """Firm Admin resets a password for a user already confirmed in their own firm."""

    new_password = forms.CharField(widget=forms.PasswordInput, min_length=8, label="New password")

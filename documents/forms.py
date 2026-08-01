from django import forms

from clients.models import Client, DocCode
from taxvault.ay import current_assessment_year


class StartBatchForm(forms.Form):
    """Section 4/7: a folder-intake run needs a folder path and an AY, pre-filled with the
    computed current AY but overridable (for back-dated/belated filing work)."""

    folder_path = forms.CharField(max_length=1000, help_text="Local folder path to scan.")
    ay = forms.CharField(max_length=10, initial=current_assessment_year)


class ReviewResolutionForm(forms.Form):
    """Section 10: staff manually assigns client and/or DocCode from the Review Queue."""

    client = forms.ModelChoiceField(queryset=Client.objects.none(), required=False)
    doc_code = forms.ModelChoiceField(queryset=DocCode.objects.none(), label="DocCode")

    def __init__(self, *args, firm=None, client_locked=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Client.objects.filter(firm=firm).order_by("name")
        self.fields["doc_code"].queryset = DocCode.objects.filter(firm=firm).order_by("code")
        if client_locked:
            del self.fields["client"]
        else:
            self.fields["client"].required = True

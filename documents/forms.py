from django import forms

from clients.models import Client, DocCode


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

"""Single logic path for writing to the Client Master table (Section 2: bulk import and
manual add write to the same table via no separate logic paths downstream)."""

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import PAN_REGEX, Category, Client


class ClientDataError(Exception):
    """Raised when client data fails validation, from either onboarding path."""


def upsert_client(firm, pan, name, phone, aadhar, category_names):
    pan = (pan or "").strip().upper()
    name = (name or "").strip()
    phone = (phone or "").strip()
    aadhar = (aadhar or "").strip()

    if not pan or not name or not phone:
        raise ClientDataError("PAN, Client Name, and Phone are required.")
    if not PAN_REGEX.match(pan):
        raise ClientDataError(f"Invalid PAN format: {pan}")

    firm_categories = {c.name.strip().lower(): c for c in Category.objects.filter(firm=firm)}
    categories = []
    unknown = []
    for cname in category_names:
        cat = firm_categories.get(cname.strip().lower())
        if cat:
            categories.append(cat)
        else:
            unknown.append(cname)
    if unknown:
        raise ClientDataError(f"Unknown category tag(s) for this firm: {', '.join(unknown)}")
    if not categories:
        raise ClientDataError("At least one category tag is required.")

    with transaction.atomic():
        existing = Client.objects.filter(firm=firm, pan=pan).first()
        client = existing or Client(firm=firm, pan=pan)
        client.name = name
        client.phone = phone
        try:
            if aadhar:
                client.set_aadhar(aadhar)
            client.full_clean(exclude=["aadhar_hash", "aadhar_masked", "categories"])
        except ValidationError as exc:
            reason = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            raise ClientDataError(reason)
        client.save()
        client.categories.set(categories)

    return client, existing is None

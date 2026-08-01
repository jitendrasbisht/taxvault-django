"""Single logic path for writing to the Client Master table (Section 2: bulk import and
manual add write to the same table via no separate logic paths downstream)."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import PAN_REGEX, Category, Client, UserProfile


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


class FirmUserError(Exception):
    """Raised when creating a Firm Admin / Staff login fails validation (Section 14)."""


def create_firm_user(firm, username, password, role):
    """The only way an in-app user is created — never touches Django's raw User admin
    or is_superuser. Section 13: firms themselves are still added only by the system admin."""
    User = get_user_model()

    username = (username or "").strip()
    role = (role or "").strip()

    if not username or not password:
        raise FirmUserError("Username and password are required.")
    if len(password) < 8:
        raise FirmUserError("Password must be at least 8 characters.")
    if role not in dict(UserProfile.ROLE_CHOICES):
        raise FirmUserError("Invalid role.")
    if User.objects.filter(username=username).exists():
        raise FirmUserError(f"Username '{username}' is already taken.")

    with transaction.atomic():
        user = User.objects.create_user(username=username, password=password, is_staff=True)
        profile = UserProfile.objects.create(user=user, firm=firm, role=role)

    return profile

def nav_counts(request):
    profile = getattr(request.user, "profile", None) if request.user.is_authenticated else None
    if not profile:
        return {}
    from clients.models import Client
    from documents.models import Document

    return {
        "nav_client_count": Client.objects.filter(firm=profile.firm).count(),
        "nav_review_count": Document.objects.filter(firm=profile.firm, review_reason__isnull=False).count(),
    }

"""Section 14: the portal is for in-app Firm Admin / Staff users only. Django superusers
(the internal system admin) use /admin/ instead — they have no firm to scope this UI to."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def portal_view(view_func):
    @login_required(login_url="portal:login")
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        profile = getattr(request.user, "profile", None)
        if profile is None:
            return redirect("/admin/" if request.user.is_superuser else "portal:login")
        return view_func(request, profile, *args, **kwargs)

    return wrapper


def firm_admin_required(view_func):
    """Firm settings (Section 14: DocCode table, category mappings, staff management)."""

    @portal_view
    @wraps(view_func)
    def wrapper(request, profile, *args, **kwargs):
        if profile.role != profile.__class__.ROLE_FIRM_ADMIN:
            from django.contrib import messages
            messages.error(request, "Only a Firm Admin can access that.")
            return redirect("portal:dashboard")
        return view_func(request, profile, *args, **kwargs)

    return wrapper

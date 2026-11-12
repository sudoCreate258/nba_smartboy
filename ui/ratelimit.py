# SPDX-License-Identifier: AGPL-3.0-or-later
"""Login rate limit shared by the app login and the Django admin login (M4-T5, review).

After TWIN_LOGIN_MAX_FAILURES failed attempts for one username or one client address
within TWIN_LOGIN_WINDOW_SECONDS, further attempts are refused. A successful login
clears both counts. Counts live in Django's default cache (one process).
"""
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse


def keys(request):
    username = (request.POST.get("username") or "").strip().lower()
    return [f"login-fail:user:{username}", f"login-fail:addr:{request.META.get('REMOTE_ADDR', '')}"]


def blocked(request):
    return any((cache.get(k) or 0) >= settings.TWIN_LOGIN_MAX_FAILURES for k in keys(request))


def record_failure(request):
    for key in keys(request):
        cache.add(key, 0, settings.TWIN_LOGIN_WINDOW_SECONDS)
        cache.incr(key)


def clear(request):
    cache.delete_many(keys(request))


def message():
    return f"Too many failed attempts. Wait {settings.TWIN_LOGIN_WINDOW_SECONDS // 60} minutes and try again."


def limit_admin_login(login_view):
    """Wrap AdminSite.login with the same limiter."""
    def view(request, extra_context=None):
        if request.method == "POST" and blocked(request):
            return HttpResponse(message(), status=429, content_type="text/plain; charset=utf-8")
        response = login_view(request, extra_context=extra_context)
        if request.method == "POST":
            if response.status_code == 200:  # the form was shown again: wrong credentials
                record_failure(request)
            elif response.status_code == 302:
                clear(request)
        return response
    return view

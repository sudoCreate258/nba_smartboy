# SPDX-License-Identifier: AGPL-3.0-or-later
"""Response headers Django does not set itself (M6 R4): Content-Security-Policy and Permissions-Policy.

The app serves everything from this host and uses no inline script or style, so the policy is
'self' only. The Django admin keeps inline style attributes in a few templates, so /admin/ also
allows inline styles (never inline scripts).
"""
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
       "font-src 'self'; manifest-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'self'; "
       "form-action 'self'; frame-ancestors 'none'")
CSP_ADMIN = CSP.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        admin = request.path.startswith("/admin/")
        response.headers.setdefault("Content-Security-Policy", CSP_ADMIN if admin else CSP)
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        return response

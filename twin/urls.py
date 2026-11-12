from django.contrib import admin
from django.urls import include, path

from ui.ratelimit import limit_admin_login

# The admin login shares the app login's rate limit (it is reachable in LAN mode too).
admin.site.login = limit_admin_login(admin.site.login)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("ui.urls")),
]

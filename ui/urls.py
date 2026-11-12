# SPDX-License-Identifier: AGPL-3.0-or-later
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "ui"

urlpatterns = [
    path("", views.home, name="home"),
    path("checkin/", views.checkin_index, name="checkin_index"),
    path("checkin/<slug:kind>/", views.checkin, name="checkin"),
    path("recent/", views.recent, name="recent"),
    path("trends/", views.trends, name="trends"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("offline/", views.offline, name="offline"),
    path("my-data/", views.export_download, name="export"),
    path("api/v0/today", views.api_today, name="api_today"),
    path("api/v0/trends", views.api_trends, name="api_trends"),
    path("api/v0/recent", views.api_recent, name="api_recent"),
    path("login/", views.RateLimitedLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]

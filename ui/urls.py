# SPDX-License-Identifier: AGPL-3.0-or-later
from django.contrib.auth import views as auth_views
from django.urls import path

from . import body, ledger_views, provenance_views, twin_ingest, views

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
    path("csrf-token/", views.csrf_token, name="csrf_token"),
    path("my-data/", views.export_download, name="export"),
    path("modules/", views.modules_page, name="modules"),
    path("permissions/", ledger_views.permissions_page, name="permissions"),
    path("permissions/revoke/<str:cid>/", ledger_views.revoke_page, name="revoke"),
    path("statement/", ledger_views.statement_page, name="statement"),
    path("provenance/", provenance_views.provenance_page, name="provenance"),
    path("body/", body.body_page, name="body"),
    path("statement/download/", ledger_views.statement_download, name="statement_download"),
    path("api/v0/today", views.api_today, name="api_today"),
    path("api/twin/minute", twin_ingest.minute, name="twin_minute_ingest"),
    path("api/v0/trends", views.api_trends, name="api_trends"),
    path("api/v0/recent", views.api_recent, name="api_recent"),
    path("login/", views.RateLimitedLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]

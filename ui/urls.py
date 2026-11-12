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
    path("login/", auth_views.LoginView.as_view(template_name="ui/login.html", redirect_authenticated_user=True),
         name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]

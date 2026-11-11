# SPDX-License-Identifier: AGPL-3.0-or-later
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from core.services.common import DISCLAIMER, STOP_TEXT

from .today import contributor_for, today


@login_required
def home(request):
    contributor = contributor_for(request.user)
    return render(request, "ui/home.html", {
        "contributor": contributor, "t": today(contributor), "disclaimer": DISCLAIMER, "stop_text": STOP_TEXT,
    })

# SPDX-License-Identifier: AGPL-3.0-or-later
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone

from core.models import DailySnapshot
from core.services.common import DISCLAIMER, STOP_TEXT
from core.services.records import save_record
from core.services.snapshots import SKIPPED, SUPERSEDED

from .forms import KINDS, ResetForm
from .today import contributor_for, today

RECENT_DAYS = 14
_IDENTITY = {"id", "cid", "contributor", "created_at"}
# Default "now" for the main time field of each kind.
_NOW_FIELDS = {"probe": "started_at", "discomfort": "at", "reset": "at"}


def _context(contributor, **extra):
    return {"contributor": contributor, "disclaimer": DISCLAIMER, "stop_text": STOP_TEXT, **extra}


@login_required
def home(request):
    contributor = contributor_for(request.user)
    with timezone.override(contributor.tzinfo):
        return render(request, "ui/home.html", _context(contributor, t=today(contributor), kinds=KINDS))


@login_required
def checkin_index(request):
    contributor = contributor_for(request.user)
    return render(request, "ui/checkin_index.html", _context(contributor, kinds=KINDS))


def _initial(kind, form_class, supersedes, now):
    if supersedes is not None:
        fields = supersedes.domain_fields()
        return {k: (timezone.localtime(v) if isinstance(v, datetime.datetime) else v)
                for k, v in fields.items() if k in form_class._meta.fields and v is not None}
    local_now = timezone.localtime(now).replace(second=0, microsecond=0)
    if kind == "snapshot":
        return {"date": local_now.date()}
    if kind == "work":
        return {"start": local_now - datetime.timedelta(minutes=50), "end": local_now}
    return {_NOW_FIELDS[kind]: local_now}


def _instance(model, contributor, form_fields, supersedes):
    """New unsaved record. A correction starts from the old record, so fields the form
    does not show (e.g. spo2, ratings) are carried over instead of dropped."""
    record = model(contributor=contributor)
    if supersedes is not None:
        for field in model._meta.concrete_fields:
            if field.name not in _IDENTITY and field.name not in form_fields:
                setattr(record, field.attname, getattr(supersedes, field.attname))
        if hasattr(record, "replaces_cid"):
            record.replaces_cid = supersedes.cid
    elif model is DailySnapshot:
        record.source = DailySnapshot.Source.MANUAL
    return record


@login_required
def checkin(request, kind):
    if kind not in KINDS:
        raise Http404
    label, form_class = KINDS[kind]
    model = form_class._meta.model
    contributor = contributor_for(request.user)
    with timezone.override(contributor.tzinfo):
        cid = request.POST.get("supersedes") or request.GET.get("correct")
        supersedes = None
        if cid:
            supersedes = model.objects.filter(cid=cid, contributor=contributor).first()
            if supersedes is None:
                raise Http404
            if not model.objects.current().filter(pk=supersedes.pk).exists():
                messages.warning(request, "That record was already corrected; correct its current version instead.")
                return redirect("ui:recent")
        extra = {"contributor": contributor} if form_class is ResetForm else {}
        instance = _instance(model, contributor, form_class._meta.fields, supersedes)
        if request.method == "POST":
            form = form_class(request.POST, instance=instance, **extra)
            if form.is_valid():
                try:
                    record, outcome = save_record(form.instance, supersedes=supersedes, reason="app correction")
                except ValidationError as exc:
                    try:
                        form.add_error(None, exc)
                    except ValueError:  # error names a field the form does not show
                        form.add_error(None, exc.messages)
                else:
                    if outcome == SKIPPED:
                        messages.info(request, f"{label}: already saved (same content); nothing new written.")
                    elif outcome == SUPERSEDED and supersedes is not None:
                        messages.success(request, f"{label} saved as a correction; the earlier version is kept in history.")
                    else:
                        messages.success(request, f"{label} saved.")
                    return redirect("ui:home")
            form.mark_errors()
        else:
            form = form_class(initial=_initial(kind, form_class, supersedes, timezone.now()), instance=instance, **extra)
        return render(request, "ui/checkin_form.html", _context(
            contributor, form=form, kind=kind, label=label, supersedes=supersedes))


def recent_records(contributor, days=RECENT_DAYS, now=None):
    """[(kind, label, [(record, when)])] of current records from the last `days` days, newest first."""
    since = (now or timezone.now()) - datetime.timedelta(days=days)
    out = []
    for kind, (label, form_class) in KINDS.items():
        model = form_class._meta.model
        rows = model.objects.current().filter(contributor=contributor)
        if model is DailySnapshot:
            rows = rows.filter(date__gte=since.astimezone(contributor.tzinfo).date()).order_by("-date")
            items = [(r, r.date) for r in rows]
        else:
            time_field = {"work": "start"}.get(kind, _NOW_FIELDS.get(kind, "at"))
            rows = rows.filter(**{f"{time_field}__gte": since}).order_by(f"-{time_field}")
            items = [(r, getattr(r, time_field)) for r in rows]
        out.append((kind, label, items))
    return out


@login_required
def recent(request):
    contributor = contributor_for(request.user)
    with timezone.override(contributor.tzinfo):
        return render(request, "ui/recent.html", _context(contributor, groups=recent_records(contributor),
                                                          days=RECENT_DAYS))

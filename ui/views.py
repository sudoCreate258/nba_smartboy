# SPDX-License-Identifier: AGPL-3.0-or-later
import datetime
import hashlib
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from core.models import DailySnapshot
from core.services.common import DISCLAIMER, STOP_TEXT
from core.services.export import export_lines
from core.services.records import save_record
from core.services.snapshots import SKIPPED, SUPERSEDED

from .forms import KINDS, ResetForm
from .models import ModuleSetting
from .modules import enabled_ids, is_on, registry
from .today import contributor_for, today
from .trends import as_data as trends_data
from .trends import build as trends_build

RECENT_DAYS = 14
_IDENTITY = {"id", "cid", "contributor", "created_at"}
# Default "now" for the main time field of each kind.
_NOW_FIELDS = {"probe": "started_at", "discomfort": "at", "reset": "at"}


def _context(contributor, **extra):
    return {"contributor": contributor, "disclaimer": DISCLAIMER, "stop_text": STOP_TEXT, **extra}


def active_kinds(enabled=None):
    """Check-in kinds whose module is on (the snapshot form belongs to the core)."""
    enabled = enabled_ids() if enabled is None else enabled
    return {k: v for k, v in KINDS.items() if is_on("checkins", k, enabled)}


class RateLimitedLoginView(LoginView):
    """Django's login view, refusing further attempts after TWIN_LOGIN_MAX_FAILURES failures
    for one username or one address within TWIN_LOGIN_WINDOW_SECONDS."""

    template_name = "ui/login.html"
    redirect_authenticated_user = True

    def _keys(self):
        username = (self.request.POST.get("username") or "").strip().lower()
        address = self.request.META.get("REMOTE_ADDR", "")
        return [f"login-fail:user:{username}", f"login-fail:addr:{address}"]

    def _blocked(self):
        return any((cache.get(k) or 0) >= settings.TWIN_LOGIN_MAX_FAILURES for k in self._keys())

    def post(self, request, *args, **kwargs):
        if self._blocked():
            form = self.get_form()
            form.errors.clear()
            minutes = settings.TWIN_LOGIN_WINDOW_SECONDS // 60
            form.add_error(None, f"Too many failed attempts. Wait {minutes} minutes and try again.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        for key in self._keys():
            cache.add(key, 0, settings.TWIN_LOGIN_WINDOW_SECONDS)
            cache.incr(key)
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(self._keys()[0])
        return super().form_valid(form)


@login_required
def home(request):
    contributor = contributor_for(request.user)
    with timezone.override(contributor.tzinfo):
        return render(request, "ui/home.html", _context(contributor, t=today(contributor), kinds=active_kinds()))


@login_required
def checkin_index(request):
    contributor = contributor_for(request.user)
    return render(request, "ui/checkin_index.html", _context(contributor, kinds=active_kinds()))


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


def _login_or_403(view):
    """login_required, except that a replay from the offline queue gets JSON 403 instead of a redirect."""
    wrapped = login_required(view)

    def inner(request, *args, **kwargs):
        if request.headers.get("X-Offline-Replay") and not request.user.is_authenticated:
            return JsonResponse({"outcome": "login", "message": "Log in again to send saved check-ins."}, status=403)
        return wrapped(request, *args, **kwargs)
    return inner


@_login_or_403
def checkin(request, kind):
    if kind not in active_kinds():  # unknown, or its module is off
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
        replay = request.headers.get("X-Offline-Replay")  # "live" (online submit) or "queue" (sent from the phone's queue)
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
                        text = f"{label}: already saved (same content); nothing new written."
                    elif outcome == SUPERSEDED and supersedes is not None:
                        text = f"{label} saved as a correction; the earlier version is kept in history."
                    else:
                        text = f"{label} saved."
                    if replay:
                        if replay == "live":
                            messages.success(request, text)
                        return JsonResponse({"outcome": outcome, "cid": record.cid, "message": text,
                                             "redirect": reverse("ui:home")})
                    (messages.info if outcome == SKIPPED else messages.success)(request, text)
                    return redirect("ui:home")
            if replay:
                errors = {k: [str(m) for m in v] for k, v in form.errors.items()}
                return JsonResponse({"outcome": "invalid", "errors": errors,
                                     "message": " ".join(m for v in errors.values() for m in v)}, status=400)
            form.mark_errors()
        else:
            form = form_class(initial=_initial(kind, form_class, supersedes, timezone.now()), instance=instance, **extra)
        return render(request, "ui/checkin_form.html", _context(
            contributor, form=form, kind=kind, label=label, supersedes=supersedes))


def recent_records(contributor, days=RECENT_DAYS, now=None):
    """[(kind, label, [(record, when)])] of current records from the last `days` days, newest first."""
    since = (now or timezone.now()) - datetime.timedelta(days=days)
    out = []
    for kind, (label, form_class) in active_kinds().items():
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
def trends(request):
    contributor = contributor_for(request.user)
    weeks = 12 if request.GET.get("weeks") == "12" else 4
    with timezone.override(contributor.tzinfo):
        return render(request, "ui/trends.html", _context(contributor, data=trends_build(contributor, weeks=weeks)))


@login_required
@require_GET
def export_download(request):
    """'My data' button: the same JSON Lines as `manage.py export_my_data`."""
    contributor = contributor_for(request.user)
    stamp = timezone.now().astimezone(contributor.tzinfo).strftime("%Y-%m-%d")
    resp = StreamingHttpResponse((line + "\n" for line in export_lines(contributor)),
                                 content_type="application/x-ndjson; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="my-data-{contributor.handle}-{stamp}.jsonl"'
    resp["Cache-Control"] = "no-store"
    return resp


def _api(view):
    """Read-only JSON behind the same login; 403 JSON (not a redirect) when logged out."""
    def inner(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "login required"}, status=403)
        if request.method != "GET":
            return JsonResponse({"error": "read-only API"}, status=405)
        contributor = contributor_for(request.user)
        with timezone.override(contributor.tzinfo):
            data = view(request, contributor, *args, **kwargs)
        resp = JsonResponse({"api": "v0", "contributor": contributor.handle, "disclaimer": DISCLAIMER, **data},
                            encoder=DjangoJSONEncoder)
        resp["Cache-Control"] = "no-store"
        return resp
    return inner


@_api
def api_today(request, contributor):
    t = today(contributor)
    t["checkins"] = [{"label": label, "done": done, "kind": kind} for label, done, kind in t["checkins"]]
    return {"today": t}


@_api
def api_trends(request, contributor):
    weeks = 12 if request.GET.get("weeks") == "12" else 4
    return {"trends": trends_data(trends_build(contributor, weeks=weeks))}


@_api
def api_recent(request, contributor):
    groups = []
    for kind, label, items in recent_records(contributor):
        groups.append({"kind": kind, "label": label,
                       "records": [{"cid": r.cid, "when": when, "summary": str(r)} for r, when in items]})
    return {"recent": groups}


@login_required
def modules_page(request):
    """List the installed modules and switch them on or off (POST, CSRF-protected)."""
    contributor = contributor_for(request.user)
    reg = registry()
    if request.method == "POST":
        module_id = request.POST.get("module_id", "")
        if module_id not in reg:
            raise Http404
        on = request.POST.get("enabled") == "1"
        ModuleSetting.objects.update_or_create(module_id=module_id, defaults={"enabled": on})
        messages.success(request, f"{reg[module_id]['name']} turned {'on' if on else 'off'}. "
                                  "Its records are kept either way.")
        return redirect("ui:modules")
    enabled = enabled_ids()
    rows = [{"m": m, "on": mid in enabled} for mid, m in reg.items()]
    return render(request, "ui/modules.html", _context(contributor, rows=rows))


STATIC_SHELL = ["ui/app.css", "ui/offline.js", "ui/icon-192.png", "ui/icon-512.png"]


def _shell_version():
    """Changes whenever a shell file changes, so phones drop the old cache."""
    digest = hashlib.sha256()
    for name in STATIC_SHELL:
        digest.update((Path(__file__).parent / "static" / name).read_bytes())
    digest.update((Path(__file__).parent / "templates" / "ui" / "sw.js").read_bytes())
    return digest.hexdigest()[:12]


@require_GET
def manifest(request):
    """Web app manifest (public: no personal data). Installable to the home screen."""
    data = {
        "name": "Twin", "short_name": "Twin", "start_url": reverse("ui:home"), "scope": "/",
        "display": "standalone", "background_color": "#fdfdfb", "theme_color": "#0b5cad",
        "description": "Your own instance: daily check-ins and trends. Load gauge, not a medical assessment.",
        "icons": [{"src": static("ui/icon-192.png"), "sizes": "192x192", "type": "image/png"},
                  {"src": static("ui/icon-512.png"), "sizes": "512x512", "type": "image/png"}],
    }
    return JsonResponse(data, content_type="application/manifest+json")


@require_GET
def service_worker(request):
    """Served from the site root so its scope covers every page (public: no personal data)."""
    shell = [static(n) for n in STATIC_SHELL] + [reverse("ui:offline"), reverse("ui:manifest")]
    body = render(request, "ui/sw.js", {"version": _shell_version(), "shell": shell,
                                        "offline_url": reverse("ui:offline")}).content
    resp = HttpResponse(body, content_type="application/javascript; charset=utf-8")
    resp["Cache-Control"] = "no-cache"
    resp["Service-Worker-Allowed"] = "/"
    return resp


@require_GET
def offline(request):
    return render(request, "ui/offline.html", {"disclaimer": DISCLAIMER})


@login_required
def recent(request):
    contributor = contributor_for(request.user)
    with timezone.override(contributor.tzinfo):
        return render(request, "ui/recent.html", _context(contributor, groups=recent_records(contributor),
                                                          days=RECENT_DAYS))

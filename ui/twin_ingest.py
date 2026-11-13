# SPDX-License-Identifier: AGPL-3.0-or-later
"""Live ingest of dtom minutes (027 Part B): POST /api/twin/minute.

- Body: one nymbus.twin_minute.v1 JSON document, at most 64 KB.
- Auth: header X-Nymbus-Token must equal env DTOM_INGEST_TOKEN (constant-time compare). With the env
  unset every request is refused (503): no token, no endpoint.
- Origin: a browser request must come from dtom itself (http://127.0.0.1:8765 or http://localhost:8765);
  any other Origin is refused (403). CORS answers exactly those two; no cookies are used or accepted.
  CSRF is exempt for this one view only: it is authenticated by the token, not by a session.
- Idempotent on (source, t_start): the same minute again is a "duplicate" (200, nothing written); a
  different document for a stored (source, t_start) is a "conflict" (409, nothing written).
Stored as a TwinMinute record of TWIN_CONTRIBUTOR through the normal record path (validation, CID).
"""
import hmac
import json
import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from core.models import Contributor, TwinMinute
from core.services.records import save_record
from twin_metrics.dtom import DtomError, check_minute

log = logging.getLogger("dtom")
ALLOWED_ORIGINS = ("http://127.0.0.1:8765", "http://localhost:8765")
MAX_BYTES = 64 * 1024


def _cors(resp, origin):
    if origin in ALLOWED_ORIGINS:
        resp["Access-Control-Allow-Origin"] = origin
        resp["Vary"] = "Origin"
    resp["Cache-Control"] = "no-store"
    return resp


def _reply(status, origin, **body):
    return _cors(JsonResponse(body, status=status), origin)


@csrf_exempt
def minute(request):
    origin = request.headers.get("Origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        return _reply(403, None, error="origin not allowed")
    if request.method == "OPTIONS":  # CORS preflight from dtom
        resp = _cors(HttpResponse(status=204), origin)
        resp["Access-Control-Allow-Methods"] = "POST"
        resp["Access-Control-Allow-Headers"] = "Content-Type, X-Nymbus-Token"
        resp["Access-Control-Max-Age"] = "600"
        return resp
    if request.method != "POST":
        return _reply(405, origin, error="POST only")
    expected = getattr(settings, "DTOM_INGEST_TOKEN", "")
    if not expected:
        return _reply(503, origin, error="ingest is off (DTOM_INGEST_TOKEN is not set)")
    given = request.headers.get("X-Nymbus-Token", "")
    if not hmac.compare_digest(given.encode(), expected.encode()):
        log.warning("dtom ingest: bad token from %s", origin or "no origin")
        return _reply(401, origin, error="bad token")
    try:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        declared = 0
    if declared > MAX_BYTES:
        return _reply(413, origin, error=f"at most {MAX_BYTES} bytes")
    body = request.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        return _reply(413, origin, error=f"at most {MAX_BYTES} bytes")
    if request.content_type != "application/json":
        return _reply(415, origin, error="Content-Type must be application/json")
    try:
        doc = json.loads(body)
        start, end = check_minute(doc)
    except ValueError as exc:  # DtomError is a ValueError, and so is a JSON error
        return _reply(400, origin, error=str(exc) if isinstance(exc, DtomError) else "not JSON")
    try:
        who = Contributor.objects.get(handle=settings.TWIN_CONTRIBUTOR)
    except Contributor.DoesNotExist:
        return _reply(503, origin, error="the contributor of this instance does not exist")
    with transaction.atomic():
        Contributor.objects.select_for_update().get(pk=who.pk)  # one writer per contributor: no double minute
        record = TwinMinute(contributor=who, source=doc["source"], t_start=start, t_end=end, data=doc)
        existing = TwinMinute.objects.filter(contributor=who, source=doc["source"], t_start=start).first()
        if existing is not None:
            if existing.cid == record.compute_cid():
                return _reply(200, origin, outcome="duplicate", cid=existing.cid)
            return _reply(409, origin, error="a different minute is already stored for this source and t_start",
                          cid=existing.cid)
        try:
            stored, _ = save_record(record)
        except ValidationError as exc:
            return _reply(400, origin, error=" ".join(exc.messages))
    return _reply(201, origin, outcome="created", cid=stored.cid)

from urllib.parse import urlencode

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import (
    Contributor,
    DailySnapshot,
    DiscomfortCheck,
    ProbeBaseline,
    ProbeSession,
    Supersession,
    WorkBlock,
)
from .services import SKIPPED, SUPERSEDED, record_snapshot


@admin.register(Contributor)
class ContributorAdmin(admin.ModelAdmin):
    list_display = ("handle",)


class ImmutableAdmin(admin.ModelAdmin):
    """Saved records are read-only and cannot be deleted; fix them with a new record."""

    def get_readonly_fields(self, request, obj=None):
        if obj is not None:
            return [f.name for f in self.model._meta.fields]
        return ()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        existing = self.model.objects.filter(cid=obj.compute_cid()).first()
        if existing is not None:
            obj.pk, obj.cid, obj._state.adding = existing.pk, existing.cid, False
            self.message_user(request, "Identical record already exists; nothing written.", messages.WARNING)
        else:
            super().save_model(request, obj, form, change)


class CorrectableAdmin(ImmutableAdmin):
    """Adds "Save as correction": opens the add form prefilled from a record.

    The source CID travels in the `supersedes` query parameter; saving a
    different record then appends a Supersession from the source to it.
    """

    actions = ["save_as_correction"]

    @admin.action(description="Save as correction (open add form prefilled)")
    def save_as_correction(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Select exactly one record.", messages.ERROR)
            return None
        record = queryset.get()
        initial = {"contributor": record.contributor_id, "supersedes": record.cid}
        for name, value in record.domain_fields().items():
            if value is not None:
                initial[name] = value
        info = self.model._meta.app_label, self.model._meta.model_name
        return HttpResponseRedirect(reverse("admin:%s_%s_add" % info) + "?" + urlencode(initial))

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        # Query-string datetimes arrive as text; the split widget needs datetime objects.
        for field in self.model._meta.fields:
            value = initial.get(field.name)
            if field.get_internal_type() == "DateTimeField" and isinstance(value, str):
                parsed = parse_datetime(value)
                if parsed is not None and timezone.is_aware(parsed):
                    initial[field.name] = timezone.localtime(parsed)
        return initial

    def get_form(self, request, obj=None, **kwargs):
        form_class = super().get_form(request, obj, **kwargs)
        source_cid = request.GET.get("supersedes")
        model = self.model

        class CorrectionForm(form_class):
            def clean(self):
                cleaned = super().clean()
                if source_cid is None:
                    return cleaned
                old = model.objects.filter(cid=source_cid).first()
                if old is None:
                    raise ValidationError("The record to correct (supersedes) does not exist.")
                contributor = cleaned.get("contributor")
                if contributor is not None and contributor.pk != old.contributor_id:
                    raise ValidationError("A correction must have the same contributor as the record it supersedes.")
                # Lets model validation (e.g. WorkBlock overlap) ignore the record being replaced.
                self.instance.replaces_cid = old.cid
                return cleaned

        return CorrectionForm

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        old = self.model.objects.filter(cid=request.GET.get("supersedes", "")).first()
        if old is None or old.cid == obj.cid:
            return
        Supersession.record(old, obj, reason="admin correction")
        self.message_user(request, "Saved as a correction; the previous record is superseded.")


@admin.register(ProbeSession)
class ProbeSessionAdmin(CorrectableAdmin):
    list_display = ("started_at", "kind", "accuracy_pct", "move_time_cv_ratio", "location", "cid")
    list_filter = ("kind", "location", "contributor")

    @admin.display(description="move time CV (ratio)", ordering="move_time_cv")
    def move_time_cv_ratio(self, obj):
        return obj.move_time_cv


@admin.register(ProbeBaseline)
class ProbeBaselineAdmin(admin.ModelAdmin):
    list_display = ("contributor", "kind", "start", "end", "frozen_at")
    list_filter = ("kind", "contributor")


@admin.register(WorkBlock)
class WorkBlockAdmin(CorrectableAdmin):
    list_display = ("start", "end", "task_type", "location", "posture", "planned_length_min", "absorption", "effort", "cid")
    list_filter = ("task_type", "location", "posture", "contributor")


@admin.register(DiscomfortCheck)
class DiscomfortCheckAdmin(CorrectableAdmin):
    list_display = ("at", "area", "score", "trigger", "countermove", "sharp_or_numb", "cid")
    list_filter = ("area", "trigger", "countermove", "sharp_or_numb", "contributor")


@admin.register(DailySnapshot)
class DailySnapshotAdmin(ImmutableAdmin):
    list_display = ("date", "source", "bia_timing", "weight_kg", "sleep_score", "cid")
    list_filter = ("source", "bia_timing", "contributor", "date")
    date_hierarchy = "date"
    actions = ["save_as_correction"]

    @admin.action(description="Save as correction (open add form prefilled)")
    def save_as_correction(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Select exactly one snapshot.", messages.ERROR)
            return None
        record = queryset.get()
        initial = {"contributor": record.contributor_id}
        for name, value in record.domain_fields().items():
            if value is not None:
                initial[name] = value
        return HttpResponseRedirect(
            reverse("admin:core_dailysnapshot_add") + "?" + urlencode(initial)
        )

    def save_model(self, request, obj, form, change):
        record, outcome = record_snapshot(obj)
        obj.pk, obj.cid, obj._state.adding = record.pk, record.cid, False
        if outcome == SKIPPED:
            self.message_user(request, "Identical record already exists; nothing written.", messages.WARNING)
        elif outcome == SUPERSEDED:
            self.message_user(request, "Saved as a correction; the previous snapshot is superseded.")

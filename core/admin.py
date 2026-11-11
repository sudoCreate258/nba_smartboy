from urllib.parse import urlencode

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse

from .models import Contributor, DailySnapshot, ProbeSession, WorkBlock
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


@admin.register(ProbeSession)
class ProbeSessionAdmin(ImmutableAdmin):
    list_display = ("started_at", "kind", "accuracy_pct", "location", "cid")
    list_filter = ("kind", "location", "contributor")


@admin.register(WorkBlock)
class WorkBlockAdmin(ImmutableAdmin):
    list_display = ("start", "end", "task_type", "location", "absorption", "effort", "cid")
    list_filter = ("task_type", "location", "contributor")


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

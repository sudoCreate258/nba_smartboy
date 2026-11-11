from urllib.parse import urlencode

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse

from .models import Contributor, DailySnapshot
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


@admin.register(DailySnapshot)
class DailySnapshotAdmin(ImmutableAdmin):
    list_display = ("date", "source", "bia_timing", "weight_kg", "sleep_score", "cid", "supersedes")
    list_filter = ("source", "bia_timing", "contributor", "date")
    date_hierarchy = "date"
    actions = ["save_as_correction"]

    def get_exclude(self, request, obj=None):
        return None if obj is not None else ("supersedes",)

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

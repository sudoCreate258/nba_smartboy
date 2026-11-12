# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check-in forms for the five daily record types. Validation is the models' own.

Date-times are entered as local time (`datetime-local`) in the contributor's
time zone, which the view activates; Django rejects local times that are
ambiguous or skipped by a daylight-saving change.
"""
import datetime

from django import forms
from django.utils import timezone

from core.models import DailySnapshot, DiscomfortCheck, ProbeSession, Reset, WorkBlock

LOCAL_INPUT = "%Y-%m-%dT%H:%M"


class LocalDateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format=LOCAL_INPUT)


class CheckInForm(forms.ModelForm):
    """Base: local date-time widgets, numeric keyboards, aria wiring for errors."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field, forms.DateTimeField):
                field.widget = LocalDateTimeInput()
                field.input_formats = [LOCAL_INPUT, "%Y-%m-%dT%H:%M:%S"]
            elif isinstance(field, forms.DateField):
                field.widget = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
            elif isinstance(field, forms.DecimalField):
                field.widget.attrs.setdefault("inputmode", "decimal")
            elif isinstance(field, forms.IntegerField):
                field.widget.attrs.setdefault("inputmode", "numeric")
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs["rows"] = 2

    def mark_errors(self):
        """aria-invalid and aria-describedby on fields with errors (call after is_valid)."""
        for name in self.errors:
            if name in self.fields:
                attrs = self.fields[name].widget.attrs
                attrs["aria-invalid"] = "true"
                attrs["aria-describedby"] = f"err-{name}"


class SnapshotForm(CheckInForm):
    class Meta:
        model = DailySnapshot
        fields = ["date", "sleep_score", "bedtime", "wake_time", "resting_hr_sleep", "hrv", "bia_timing",
                  "weight_kg", "body_fat_pct", "skeletal_muscle_kg", "bmr_kcal", "notes"]
        labels = {"resting_hr_sleep": "Resting HR (sleep)", "hrv": "HRV", "bia_timing": "Body composition timing",
                  "bmr_kcal": "BMR (kcal)"}
        help_texts = {"bia_timing": "Body composition is only valid before a session, never after the sauna."}


class ProbeForm(CheckInForm):
    class Meta:
        model = ProbeSession
        fields = ["started_at", "kind", "n_items", "accuracy_pct", "median_solve_s", "blunders", "late_blunders",
                  "fast_blunders", "move_time_cv", "time_control", "location", "notes"]
        labels = {"started_at": "Started", "accuracy_pct": "Accuracy (%)", "median_solve_s": "Median solve time (s)",
                  "move_time_cv": "Move time CV (ratio)"}


class WorkBlockForm(CheckInForm):
    class Meta:
        model = WorkBlock
        fields = ["start", "end", "task_type", "location", "posture", "planned_length_min", "interruptions",
                  "absorption", "effort", "notes"]
        labels = {"planned_length_min": "Planned length (min)", "absorption": "Absorption (1-5)",
                  "effort": "Effort (1-5)"}


class DiscomfortForm(CheckInForm):
    class Meta:
        model = DiscomfortCheck
        fields = ["at", "area", "score", "trigger", "countermove", "sharp_or_numb", "notes"]
        labels = {"at": "Time", "score": "Score (0-10)", "sharp_or_numb": "Sharp pain or numbness"}


class ResetForm(CheckInForm):
    """The two probes are picked from recent mini-puzzle sessions instead of typing CIDs."""

    before_probe_cid = forms.ChoiceField(label="Mini-probe before")
    after_probe_cid = forms.ChoiceField(label="Mini-probe after")

    class Meta:
        model = Reset
        fields = ["at", "kind", "duration_min", "before_probe_cid", "after_probe_cid", "notes"]
        labels = {"at": "Time", "duration_min": "Duration (min)"}

    def __init__(self, *args, contributor=None, **kwargs):
        super().__init__(*args, **kwargs)
        since = timezone.now() - datetime.timedelta(days=3)
        recent = (ProbeSession.objects.current()
                  .filter(contributor=contributor, kind=ProbeSession.Kind.MINI_PUZZLE, started_at__gte=since)
                  .order_by("-started_at"))
        choices = [("", "Choose a mini-probe")]
        for p in recent:
            acc = "" if p.accuracy_pct is None else f", {p.accuracy_pct}%"
            choices.append((p.cid, f"{timezone.localtime(p.started_at):%a %H:%M}{acc}"))
        # A correction may reference a probe older than 3 days; keep it selectable.
        for name in ("before_probe_cid", "after_probe_cid"):
            current = self.initial.get(name) or getattr(self.instance, name, "")
            if current and current not in dict(choices):
                choices.append((current, f"{current[:16]}..."))
        self.fields["before_probe_cid"].choices = choices
        self.fields["after_probe_cid"].choices = choices


KINDS = {
    "snapshot": ("Daily snapshot", SnapshotForm),
    "probe": ("Probe", ProbeForm),
    "work": ("Work block", WorkBlockForm),
    "discomfort": ("Discomfort check", DiscomfortForm),
    "reset": ("Reset", ResetForm),
}


class GrantForm(forms.Form):
    """Grant one simulated recipient read access to one category (M5). Starts now."""

    recipient = forms.ChoiceField(label="Recipient")
    purpose = forms.CharField(label="Purpose", max_length=500, help_text="Why this recipient may read the data.")
    end = forms.DateTimeField(label="Ends (optional)", required=False, widget=LocalDateTimeInput(),
                              input_formats=[LOCAL_INPUT, "%Y-%m-%dT%H:%M:%S"],
                              help_text="Leave empty to keep it until you revoke it.")

    def __init__(self, *args, **kwargs):
        from ledger.models import Recipient

        super().__init__(*args, **kwargs)
        self.fields["recipient"].choices = Recipient.choices

    def clean_end(self):
        end = self.cleaned_data.get("end")
        if end is not None and end <= timezone.now():
            raise forms.ValidationError("The end must be in the future.")
        return end


class RevokeForm(forms.Form):
    reason = forms.CharField(label="Reason (optional)", max_length=200, required=False)
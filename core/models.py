from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from nymbus.provenance import canonical_bytes, compute_cid

_NON_CONTENT_FIELDS = {"cid", "contributor", "supersedes", "created_at"}


class ImmutableRecordError(Exception):
    """Raised when a saved, CID-keyed record is modified."""


class Contributor(models.Model):
    handle = models.CharField(max_length=64, unique=True)

    def __str__(self):
        return self.handle


class RecordQuerySet(models.QuerySet):
    def current(self):
        """Records that no other record supersedes."""
        return self.filter(successors__isnull=True)


class ProvenancedRecord(models.Model):
    """Abstract base: immutable record keyed by a CID over its canonical content.

    Subclasses set `record_kind` and implement `domain_fields()`.
    """

    record_kind = ""

    cid = models.CharField(max_length=128, unique=True, editable=False)
    contributor = models.ForeignKey(Contributor, on_delete=models.PROTECT)
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="successors",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = RecordQuerySet.as_manager()

    class Meta:
        abstract = True

    def domain_fields(self):
        """Content fields that feed the CID (identity and ingest metadata excluded).

        Values are coerced to their field type first so that 97.8, "97.8" and
        Decimal("97.80") all yield the same canonical form.
        """
        out = {}
        for field in self._meta.concrete_fields:
            if field.primary_key or field.name in _NON_CONTENT_FIELDS:
                continue
            value = field.to_python(getattr(self, field.attname))
            if isinstance(value, Decimal):
                value = value.quantize(Decimal(1).scaleb(-field.decimal_places))
            out[field.name] = value
        return out

    def compute_cid(self):
        return compute_cid(
            canonical_bytes(self.record_kind, self.contributor.handle, self.domain_fields())
        )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError(
                f"{type(self).__name__} {self.cid} is immutable; "
                "create a new record that supersedes it"
            )
        self.cid = self.compute_cid()
        super().save(*args, **kwargs)


class DailySnapshot(ProvenancedRecord):
    record_kind = "daily_snapshot"

    class BiaTiming(models.TextChoices):
        PRE_SESSION = "pre_session"
        POST_SAUNA = "post_sauna"
        UNKNOWN = "unknown"

    class Source(models.TextChoices):
        SAMSUNG_HEALTH = "samsung_health"
        SECA = "seca"
        MANUAL = "manual"

    # Body-composition readings that a post-sauna BIA makes invalid.
    BODY_COMPOSITION_FIELDS = ("body_fat_pct", "skeletal_muscle_kg", "bmr_kcal")

    date = models.DateField()
    sleep_score = models.PositiveSmallIntegerField(null=True, blank=True)
    bedtime = models.TimeField(null=True, blank=True)
    wake_time = models.TimeField(null=True, blank=True)
    sleep_duration_min = models.PositiveSmallIntegerField(null=True, blank=True)
    resting_hr_sleep = models.PositiveSmallIntegerField(null=True, blank=True)
    hrv = models.PositiveSmallIntegerField(null=True, blank=True)
    spo2 = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    body_fat_pct = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    skeletal_muscle_kg = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True
    )
    bmr_kcal = models.PositiveSmallIntegerField(null=True, blank=True)
    bia_timing = models.CharField(
        max_length=16, choices=BiaTiming.choices, default=BiaTiming.UNKNOWN
    )
    source = models.CharField(max_length=16, choices=Source.choices)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.date} {self.source} {self.cid[:12]}"

    def clean(self):
        if self.bia_timing == self.BiaTiming.POST_SAUNA:
            set_fields = [
                f for f in self.BODY_COMPOSITION_FIELDS if getattr(self, f) is not None
            ]
            if set_fields:
                raise ValidationError(
                    "Post-sauna BIA readings are invalid; body composition must be "
                    f"empty (set: {', '.join(set_fields)})."
                )

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.clean()
        super().save(*args, **kwargs)


class ProbeSession(ProvenancedRecord):
    record_kind = "probe_session"

    class Kind(models.TextChoices):
        PUZZLE_SET = "puzzle_set"
        RAPID_GAME = "rapid_game"
        MODULE = "module"

    class Location(models.TextChoices):
        OFFICE = "office"
        REMOTE = "remote"
        OTHER = "other"

    started_at = models.DateTimeField()
    kind = models.CharField(max_length=16, choices=Kind.choices)
    time_control = models.CharField(max_length=32, null=True, blank=True)
    n_items = models.PositiveSmallIntegerField(null=True, blank=True)
    accuracy_pct = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    median_solve_s = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    blunders = models.PositiveSmallIntegerField(null=True, blank=True)
    late_blunders = models.PositiveSmallIntegerField(null=True, blank=True)
    fast_blunders = models.PositiveSmallIntegerField(null=True, blank=True)
    opponent_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    own_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    location = models.CharField(max_length=16, choices=Location.choices, null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.kind} {self.started_at:%Y-%m-%d %H:%M} {self.cid[:12]}"


class WorkBlock(ProvenancedRecord):
    record_kind = "work_block"

    class TaskType(models.TextChoices):
        CODE = "code"
        MEETING = "meeting"
        ADMIN = "admin"
        STUDY = "study"
        OTHER = "other"

    class Location(models.TextChoices):
        OFFICE = "office"
        REMOTE = "remote"
        COMMUTE = "commute"

    start = models.DateTimeField()
    end = models.DateTimeField()
    task_type = models.CharField(max_length=16, choices=TaskType.choices)
    location = models.CharField(max_length=16, choices=Location.choices, null=True, blank=True)
    interruptions = models.PositiveSmallIntegerField(null=True, blank=True)
    absorption = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    effort = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-start"]
        constraints = [
            models.CheckConstraint(condition=models.Q(end__gt=models.F("start")), name="workblock_end_after_start"),
            models.CheckConstraint(
                condition=models.Q(absorption__isnull=True) | models.Q(absorption__range=(1, 5)),
                name="workblock_absorption_1_5",
            ),
            models.CheckConstraint(
                condition=models.Q(effort__isnull=True) | models.Q(effort__range=(1, 5)),
                name="workblock_effort_1_5",
            ),
        ]

    def __str__(self):
        return f"{self.task_type} {self.start:%Y-%m-%d %H:%M} {self.cid[:12]}"

    @property
    def duration(self):
        """Derived, never stored."""
        return self.end - self.start

    def clean(self):
        if self.start and self.end and self.end <= self.start:
            raise ValidationError("end must be after start.")
        for name in ("absorption", "effort"):
            value = getattr(self, name)
            if value is not None and not 1 <= value <= 5:
                raise ValidationError(f"{name} must be between 1 and 5.")

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.clean()
        super().save(*args, **kwargs)

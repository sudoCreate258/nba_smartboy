import datetime
import zoneinfo
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import F, OuterRef, Q, Subquery
from django.utils import timezone

from nymbus.provenance import canonical_bytes, compute_cid

_NON_CONTENT_FIELDS = {"cid", "contributor", "created_at"}


class ImmutableRecordError(Exception):
    """Raised when a saved, CID-keyed record is modified."""


def validate_timezone(value):
    try:
        zoneinfo.ZoneInfo(value)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        raise ValidationError(f"Unknown time zone: {value!r}")


class Contributor(models.Model):
    handle = models.CharField(max_length=64, unique=True)
    timezone = models.CharField(
        max_length=64, default="America/New_York", validators=[validate_timezone]
    )

    @property
    def tzinfo(self):
        return zoneinfo.ZoneInfo(self.timezone)

    def __str__(self):
        return self.handle


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableRecordError("Records are immutable; create a superseding record.")

    def bulk_update(self, *args, **kwargs):
        raise ImmutableRecordError("Records are immutable; create a superseding record.")

    def delete(self):
        raise ImmutableRecordError("Records are immutable and cannot be deleted.")


class RecordQuerySet(AppendOnlyQuerySet):
    def current(self):
        """Records that are not superseded.

        A record is current when the most recent Supersession touching its CID
        (as old or new) points to it, or when no Supersession touches it. A
        revert (A -> B -> A) therefore makes A current again without a new row.
        """
        latest_new = (
            Supersession.objects.filter(Q(old_cid=OuterRef("cid")) | Q(new_cid=OuterRef("cid")))
            .order_by("-id")
            .values("new_cid")[:1]
        )
        return self.annotate(_latest_new_cid=Subquery(latest_new)).filter(
            Q(_latest_new_cid__isnull=True) | Q(_latest_new_cid=F("cid"))
        )


class Supersession(models.Model):
    """Append-only event: `new_cid` replaces `old_cid` as the current record."""

    old_cid = models.CharField(max_length=128)
    new_cid = models.CharField(max_length=128)
    contributor = models.ForeignKey(Contributor, on_delete=models.PROTECT)
    reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        indexes = [
            models.Index(fields=["contributor", "new_cid", "created_at"]),
            models.Index(fields=["old_cid"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(old_cid=F("new_cid")), name="supersession_old_ne_new"
            ),
        ]

    def __str__(self):
        return f"{self.old_cid[:12]} -> {self.new_cid[:12]}"

    @classmethod
    def record(cls, old, new, reason=""):
        """Append a Supersession from saved record `old` to saved record `new`."""
        if type(old) is not type(new):
            raise ValidationError("A record can only supersede one of the same kind.")
        if old.contributor_id != new.contributor_id:
            raise ValidationError("A record can only supersede one from the same contributor.")
        if old.cid == new.cid:
            raise ValidationError("A record cannot supersede itself.")
        return cls.objects.create(
            old_cid=old.cid, new_cid=new.cid, contributor_id=new.contributor_id, reason=reason
        )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError("Supersession events are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Supersession events cannot be deleted.")


class ProvenancedRecord(models.Model):
    """Abstract base: immutable record keyed by a CID over its canonical content.

    Subclasses set `record_kind` and implement `domain_fields()`.
    """

    record_kind = ""

    cid = models.CharField(max_length=128, unique=True, editable=False)
    contributor = models.ForeignKey(Contributor, on_delete=models.PROTECT)
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

    def clean(self):
        for field in self._meta.concrete_fields:
            if isinstance(field, models.DateTimeField) and field.name != "created_at":
                value = getattr(self, field.attname)
                if isinstance(value, datetime.datetime) and timezone.is_naive(value):
                    raise ValidationError({field.name: "Naive datetimes are not allowed; include a time zone."})

    def validate(self):
        """Field and model validation; cid is set on save."""
        # Trailing zeros are not extra precision: Decimal("97.80") is 97.8.
        for field in self._meta.concrete_fields:
            if isinstance(field, models.DecimalField):
                try:
                    value = field.to_python(getattr(self, field.attname))
                except ValidationError:
                    continue  # reported by full_clean below
                if isinstance(value, Decimal) and value.is_finite():
                    places = Decimal(1).scaleb(-field.decimal_places)
                    if value == value.quantize(places):
                        value = value.quantize(places)
                    setattr(self, field.attname, value)
        self.full_clean(exclude=["cid"], validate_unique=False)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError(
                f"{type(self).__name__} {self.cid} is immutable; "
                "create a new record that supersedes it"
            )
        self.validate()
        self.cid = self.compute_cid()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError(f"{type(self).__name__} {self.cid} cannot be deleted.")


PCT = [MinValueValidator(0), MaxValueValidator(100)]


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
    sleep_score = models.PositiveSmallIntegerField(null=True, blank=True, validators=PCT)
    bedtime = models.DateTimeField(null=True, blank=True)
    wake_time = models.DateTimeField(null=True, blank=True)
    sleep_duration_min = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(1440)]
    )
    resting_hr_sleep = models.PositiveSmallIntegerField(null=True, blank=True)
    hrv = models.PositiveSmallIntegerField(null=True, blank=True)
    spo2 = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True, validators=PCT
    )
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    body_fat_pct = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True, validators=PCT
    )
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

    def current_for_date(self):
        """The current snapshot for this contributor and date, or None."""
        return (
            type(self)
            .objects.current()
            .filter(contributor_id=self.contributor_id, date=self.date)
            .first()
        )

    def save(self, *args, supersede=False, reason="", **kwargs):
        """The only write path for snapshots.

        Takes the contributor-row lock and refuses to create a second current
        snapshot for the same contributor and date. With supersede=True the new
        record replaces the current one and a Supersession is recorded.
        """
        if not self._state.adding:
            return super().save(*args, **kwargs)  # raises ImmutableRecordError
        with transaction.atomic():
            self.validate()
            Contributor.objects.select_for_update().get(pk=self.contributor_id)
            current = self.current_for_date()
            if current is not None and not supersede:
                raise ValidationError(
                    f"A current snapshot already exists for {self.date}; "
                    "save with supersede=True to replace it."
                )
            super().save(*args, **kwargs)
            if current is not None:
                Supersession.record(current, self, reason=reason)

    def clean(self):
        super().clean()
        if (
            self.contributor_id
            and isinstance(self.date, datetime.date)
            and isinstance(self.wake_time, datetime.datetime)
            and timezone.is_aware(self.wake_time)
        ):
            local_date = self.wake_time.astimezone(self.contributor.tzinfo).date()
            if self.date != local_date:
                raise ValidationError(
                    {"date": f"date must be the wake_time date in {self.contributor.timezone} ({local_date})."}
                )
        if self.bia_timing == self.BiaTiming.POST_SAUNA:
            set_fields = [
                f for f in self.BODY_COMPOSITION_FIELDS if getattr(self, f) is not None
            ]
            if set_fields:
                raise ValidationError(
                    "Post-sauna BIA readings are invalid; body composition must be "
                    f"empty (set: {', '.join(set_fields)})."
                )


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
    accuracy_pct = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True, validators=PCT
    )
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

    def clean(self):
        super().clean()
        if self.blunders is not None:
            for name in ("late_blunders", "fast_blunders"):
                value = getattr(self, name)
                if value is not None and value > self.blunders:
                    raise ValidationError(f"{name} cannot exceed blunders.")

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
        super().clean()
        if self.start and self.end and self.end <= self.start:
            raise ValidationError("end must be after start.")
        for name in ("absorption", "effort"):
            value = getattr(self, name)
            if value is not None and not 1 <= value <= 5:
                raise ValidationError(f"{name} must be between 1 and 5.")

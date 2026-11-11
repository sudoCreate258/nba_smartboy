import datetime
import zoneinfo
from decimal import Context, Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import F, OuterRef, Q, Subquery
from django.utils import timezone

from nymbus.provenance import canonical_bytes, compute_cid

_NON_CONTENT_FIELDS = {"cid", "contributor", "created_at"}


_WIDE = Context(prec=60)


def quantize_decimal(field, value):
    """Quantize to the field's decimal places; ValidationError naming the field if impossible."""
    if not value.is_finite():
        raise ValidationError({field.name: "Must be a finite number."})
    try:
        return value.quantize(Decimal(1).scaleb(-field.decimal_places), context=_WIDE)
    except InvalidOperation:
        raise ValidationError({field.name: "Number is out of range."})


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


MAX_CHAIN = 50  # guard when following correction chains


class Lineage:
    """Correction chains of one contributor, loaded once, followed in memory.

    A record's "lineage" is every CID whose chain of corrections ends at the same
    current record. Records that point to another record by CID (sets to their
    session, resets to their probes) use it so that correcting the target does
    not orphan what points to it.
    """

    def __init__(self, contributor_id):
        self.next = dict(
            Supersession.objects.filter(contributor_id=contributor_id).order_by("id").values_list("old_cid", "new_cid")
        )  # later events win

    def resolve(self, cid, current_cids):
        """The CID in current_cids that cid's chain ends at, or None."""
        for _ in range(MAX_CHAIN):
            if cid in current_cids:
                return cid
            if cid not in self.next:
                return None
            cid = self.next[cid]
        return None

    def group(self, current_cids):
        """{member CID: current CID} for every CID whose chain ends at one of current_cids."""
        current_cids = set(current_cids)
        out = {cid: cid for cid in current_cids}
        for cid in self.next:
            found = self.resolve(cid, current_cids)
            if found is not None:
                out[cid] = found
        return out

    def members(self, current_cid):
        """Every CID whose chain ends at current_cid (including itself)."""
        return set(self.group({current_cid}))


class ProvenancedRecord(models.Model):
    """Abstract base: immutable record keyed by a CID over its canonical content.

    Subclasses set `record_kind` and implement `domain_fields()`.
    """

    record_kind = ""
    # Fields added after records existed. A null value is left out of the canonical
    # content, so records created before the field keep their CID. Any future nullable
    # field must be listed here (see DECISIONS, "Canonicalization of new nullable fields").
    OMIT_IF_NULL = ()

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
                value = quantize_decimal(field, value)
            if value is None and field.name in self.OMIT_IF_NULL:
                continue
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
        errors = {}
        for field in self._meta.concrete_fields:
            if isinstance(field, models.DecimalField):
                try:
                    value = field.to_python(getattr(self, field.attname))
                    if isinstance(value, Decimal):
                        quantized = quantize_decimal(field, value)
                        if value == quantized:
                            setattr(self, field.attname, quantized)
                except ValidationError as exc:
                    errors.update(exc.message_dict if hasattr(exc, "error_dict") else {field.name: exc.messages})
        if errors:
            raise ValidationError(errors)
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
    BODY_COMPOSITION_FIELDS = ("weight_kg", "body_fat_pct", "skeletal_muscle_kg", "bmr_kcal")

    date = models.DateField()
    sleep_score = models.PositiveSmallIntegerField(null=True, blank=True, validators=PCT)
    bedtime = models.DateTimeField(null=True, blank=True)
    wake_time = models.DateTimeField(null=True, blank=True)
    sleep_duration_min = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(1440)]
    )
    resting_hr_sleep = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(20), MaxValueValidator(150)]
    )
    hrv = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(300)]
    )
    spo2 = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True, validators=PCT
    )
    weight_kg = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(30), MaxValueValidator(300)],
    )
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
    OMIT_IF_NULL = ("move_time_cv",)

    class Kind(models.TextChoices):
        PUZZLE_SET = "puzzle_set"
        RAPID_GAME = "rapid_game"
        MODULE = "module"
        MINI_PUZZLE = "mini_puzzle"  # about 5 puzzles between work blocks (M3)

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
    move_time_cv = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
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
    OMIT_IF_NULL = ("posture", "planned_length_min")

    class Posture(models.TextChoices):
        SIT = "sit"
        STAND = "stand"
        MIXED = "mixed"

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
    # Added in M3 (both in OMIT_IF_NULL, so earlier CIDs are unchanged).
    posture = models.CharField(max_length=8, choices=Posture.choices, null=True, blank=True)
    planned_length_min = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(240)],
        help_text="Pomodoro length the block was planned at, e.g. 25, 40 or 50.",
    )

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

    # CID of the block this one corrects; set by the correction path so the
    # correction may overlap the record it replaces. Not a field, not in the CID.
    replaces_cid = None

    def overlapping(self):
        """Current blocks of the same contributor that overlap this one (touching is fine).

        Excludes the block being corrected and an identical record (same CID),
        which is a duplicate, not an overlap.
        """
        others = WorkBlock.objects.current().filter(
            contributor_id=self.contributor_id, start__lt=self.end, end__gt=self.start
        )
        if self.pk:
            others = others.exclude(pk=self.pk)
        skip = {self.replaces_cid} if self.replaces_cid else set()
        try:
            skip.add(self.compute_cid())
        except (ValidationError, Contributor.DoesNotExist):
            pass
        return others.exclude(cid__in=skip)

    def clean(self):
        super().clean()
        if self.start and self.end and self.end <= self.start:
            raise ValidationError("end must be after start.")
        for name in ("absorption", "effort"):
            value = getattr(self, name)
            if value is not None and not 1 <= value <= 5:
                raise ValidationError(f"{name} must be between 1 and 5.")
        if self.contributor_id and isinstance(self.start, datetime.datetime) and isinstance(self.end, datetime.datetime):
            clash = self.overlapping().first()
            if clash is not None:
                tz = self.contributor.tzinfo
                s, e = clash.start.astimezone(tz), clash.end.astimezone(tz)
                raise ValidationError(
                    f"Overlaps work block {s:%Y-%m-%d %H:%M}-{e:%H:%M} {self.contributor.timezone} "
                    f"({clash.cid[:12]}); correct that block instead of adding an overlapping one."
                )

    def save(self, *args, **kwargs):
        """Serializes the overlap check and insert per contributor (row lock), so two
        concurrent overlapping blocks cannot both pass validation."""
        if not self._state.adding:
            return super().save(*args, **kwargs)  # raises ImmutableRecordError
        with transaction.atomic():
            Contributor.objects.select_for_update().get(pk=self.contributor_id)
            super().save(*args, **kwargs)

class DiscomfortCheck(ProvenancedRecord):
    """A quick discomfort rating. sharp_or_numb is a stop signal, not a score."""

    record_kind = "discomfort_check"

    class Area(models.TextChoices):
        NECK = "neck"
        SHOULDER = "shoulder"
        WRIST = "wrist"
        HIP = "hip"
        LOW_BACK = "low_back"
        OTHER = "other"

    class Trigger(models.TextChoices):
        END_OF_COMMUTE = "end_of_commute"
        END_OF_MEETING = "end_of_meeting"
        END_OF_BLOCK = "end_of_block"
        STANDING_LONG = "standing_long"
        OTHER = "other"

    class Countermove(models.TextChoices):
        NONE = "none"
        HIP_FLEXOR = "hip_flexor"
        CHIN_TUCK_PULLAPART = "chin_tuck_pullapart"
        WRIST_MOBILITY = "wrist_mobility"
        DEAD_HANG = "dead_hang"
        CALF_WEIGHT_SHIFT = "calf_weight_shift"
        WALK = "walk"
        OTHER = "other"

    at = models.DateTimeField()
    area = models.CharField(max_length=16, choices=Area.choices)
    score = models.PositiveSmallIntegerField(validators=[MaxValueValidator(10)])
    trigger = models.CharField(max_length=16, choices=Trigger.choices)
    countermove = models.CharField(max_length=24, choices=Countermove.choices, default=Countermove.NONE)
    sharp_or_numb = models.BooleanField(
        default=False, help_text="Sharp pain or numbness: stop the block and get it checked by a professional."
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(score__lte=10), name="discomfortcheck_score_0_10"),
        ]

    def __str__(self):
        return f"{self.area} {self.score} {self.at:%Y-%m-%d %H:%M} {self.cid[:12]}"


class Reset(ProvenancedRecord):
    """A short reset between work blocks, bracketed by two mini-probes.

    before_probe_cid / after_probe_cid are plain CID strings (same rule as
    Supersession). kind "none" is the control condition.
    """

    record_kind = "reset"

    class Kind(models.TextChoices):
        WALK = "walk"
        COLD_SHOWER = "cold_shower"
        DEAD_HANG_MOBILITY = "dead_hang_mobility"
        BREATHING = "breathing"
        NAP = "nap"
        NONE = "none"

    at = models.DateTimeField()
    kind = models.CharField(max_length=20, choices=Kind.choices)
    duration_min = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(240)])
    before_probe_cid = models.CharField(max_length=128, help_text="CID of the mini_puzzle session taken before.")
    after_probe_cid = models.CharField(max_length=128, help_text="CID of the mini_puzzle session taken after.")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-at"]

    def __str__(self):
        return f"{self.kind} {self.at:%Y-%m-%d %H:%M} {self.cid[:12]}"

    def clean(self):
        super().clean()
        if not (self.contributor_id and isinstance(self.at, datetime.datetime)):
            return
        errors = {}
        for name, side in (("before_probe_cid", "before"), ("after_probe_cid", "after")):
            cid = getattr(self, name)
            if not cid:
                continue  # required-field error comes from field validation
            session = ProbeSession.objects.current().filter(cid=cid).first()
            if session is None:
                errors[name] = "Must be the CID of a current probe session."
            elif session.contributor_id != self.contributor_id:
                errors[name] = "Must be a probe session of the same contributor."
            elif session.kind != ProbeSession.Kind.MINI_PUZZLE:
                errors[name] = "Must be a mini_puzzle session."
            elif side == "before" and not session.started_at < self.at:
                errors[name] = "The before probe must start before the reset."
            elif side == "after" and not session.started_at > self.at:
                errors[name] = "The after probe must start after the reset."
        if errors:
            raise ValidationError(errors)


class WeeklyCheck(ProvenancedRecord):
    """Weekly self-rated burnout check. Only the instrument name and score are
    stored; questionnaire item text is never stored or shipped."""

    record_kind = "weekly_check"

    week_start = models.DateField(help_text="Local Monday of the week.")
    instrument = models.CharField(max_length=100, help_text="Name of the questionnaire used.")
    score = models.DecimalField(max_digits=6, decimal_places=2, validators=[MinValueValidator(0)])
    scale_max = models.DecimalField(max_digits=6, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-week_start"]

    def __str__(self):
        return f"{self.instrument} {self.week_start} {self.score}/{self.scale_max} {self.cid[:12]}"

    def clean(self):
        super().clean()
        if isinstance(self.week_start, datetime.date) and self.week_start.weekday() != 0:
            raise ValidationError({"week_start": "week_start must be a Monday."})
        if self.instrument is not None and not self.instrument.strip():
            raise ValidationError({"instrument": "Name the questionnaire used."})
        try:
            score, scale_max = Decimal(str(self.score)), Decimal(str(self.scale_max))
        except (InvalidOperation, TypeError, ValueError):
            return  # field validation reports it
        if score.is_finite() and scale_max.is_finite() and score > scale_max:
            raise ValidationError({"score": "score cannot exceed scale_max."})


RATING_0_3 = [MinValueValidator(0), MaxValueValidator(3)]


class TrainingSession(ProvenancedRecord):
    """A strength or conditioning session (RP-style programming fields)."""

    record_kind = "training_session"

    class Location(models.TextChoices):
        GYM = "gym"
        HOME = "home"
        OTHER = "other"

    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    program = models.CharField(max_length=100, blank=True, help_text='Free text, e.g. "RP Hypertrophy".')
    mesocycle = models.CharField(max_length=100, blank=True)
    meso_week = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    is_deload = models.BooleanField(default=False)
    location = models.CharField(max_length=8, choices=Location.choices, null=True, blank=True)
    session_rpe = models.DecimalField(
        max_digits=3, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        label = self.program or "session"
        return f"{label} {self.started_at:%Y-%m-%d %H:%M} {self.cid[:12]}"

    def clean(self):
        super().clean()
        if isinstance(self.started_at, datetime.datetime) and isinstance(self.ended_at, datetime.datetime):
            if self.ended_at <= self.started_at:
                raise ValidationError({"ended_at": "ended_at must be after started_at."})


def normalize_exercise(value):
    """Lower case, trimmed, inner whitespace collapsed: "  Bench  Press " -> "bench press"."""
    return " ".join(value.split()).lower() if isinstance(value, str) else value


class TrainingSet(ProvenancedRecord):
    """One set of a TrainingSession, referenced by the session's CID.

    joint_pain >= 2 is a stop signal (same wording as discomfort).
    """

    record_kind = "training_set"
    STOP_JOINT_PAIN = 2

    class MuscleGroup(models.TextChoices):
        CHEST = "chest"
        BACK = "back"
        SHOULDERS = "shoulders"
        BICEPS = "biceps"
        TRICEPS = "triceps"
        QUADS = "quads"
        HAMSTRINGS = "hamstrings"
        GLUTES = "glutes"
        CALVES = "calves"
        ABS = "abs"
        FOREARMS = "forearms"
        FULL_BODY = "full_body"
        OTHER = "other"

    session_cid = models.CharField(max_length=128, help_text="CID of the TrainingSession.")
    order = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    exercise = models.CharField(max_length=100)
    muscle_group = models.CharField(max_length=12, choices=MuscleGroup.choices)
    load_kg = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    reps = models.PositiveSmallIntegerField(validators=[MaxValueValidator(1000)])
    rir = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(10)],
                                           help_text="Reps in reserve.")
    pump = models.PositiveSmallIntegerField(null=True, blank=True, validators=RATING_0_3)
    soreness_before = models.PositiveSmallIntegerField(null=True, blank=True, validators=RATING_0_3)
    joint_pain = models.PositiveSmallIntegerField(null=True, blank=True, validators=RATING_0_3)
    joint_pain_area = models.CharField(max_length=16, choices=DiscomfortCheck.Area.choices, null=True, blank=True)
    notes = models.TextField(blank=True)

    # CID of the set this one corrects (set by the correction path); not a field.
    replaces_cid = None

    class Meta:
        ordering = ["session_cid", "order"]

    def __str__(self):
        return f"{self.order}. {self.exercise} {self.reps} reps {self.cid[:12]}"

    def normalize(self):
        self.exercise = normalize_exercise(self.exercise)

    def compute_cid(self):
        self.normalize()
        return super().compute_cid()

    def validate(self):
        self.normalize()
        super().validate()

    @property
    def is_stop_signal(self):
        return self.joint_pain is not None and self.joint_pain >= self.STOP_JOINT_PAIN

    def clean(self):
        super().clean()
        if self.joint_pain_area and self.joint_pain is None:
            raise ValidationError({"joint_pain": "Give a joint pain score (0-3) when a joint-pain area is set."})
        if not self.contributor_id or not self.session_cid:
            return
        session = TrainingSession.objects.current().filter(cid=self.session_cid).first()
        if session is None:
            raise ValidationError({"session_cid": "Must be the CID of a current training session."})
        if session.contributor_id != self.contributor_id:
            raise ValidationError({"session_cid": "Must be a training session of the same contributor."})
        if self.order:
            skip = {self.replaces_cid} if self.replaces_cid else set()
            try:
                skip.add(self.compute_cid())
            except (ValidationError, Contributor.DoesNotExist):
                pass
            # Sets attached to earlier versions of this session belong to it too.
            lineage = Lineage(self.contributor_id).members(session.cid)
            clash = (TrainingSet.objects.current()
                     .filter(session_cid__in=lineage, order=self.order).exclude(cid__in=skip).first())
            if clash is not None:
                raise ValidationError(
                    {"order": f"Set {self.order} already exists in this session ({clash.cid[:12]}); correct it instead."}
                )

    def save(self, *args, **kwargs):
        """Serializes the order check and insert per contributor (row lock)."""
        if not self._state.adding:
            return super().save(*args, **kwargs)  # raises ImmutableRecordError
        with transaction.atomic():
            Contributor.objects.select_for_update().get(pk=self.contributor_id)
            super().save(*args, **kwargs)


class ProbeBaseline(models.Model):
    """Owner-set baseline window for one probe kind.

    Configuration, not contributed data: it has no CID and may be edited. The
    newest `frozen_at` per contributor and kind wins.
    """

    contributor = models.ForeignKey(Contributor, on_delete=models.PROTECT)
    kind = models.CharField(max_length=16, choices=ProbeSession.Kind.choices)
    start = models.DateTimeField()
    end = models.DateTimeField()
    frozen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-frozen_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(end__gt=models.F("start")), name="probebaseline_end_after_start"),
        ]

    def __str__(self):
        return f"{self.contributor} {self.kind} {self.start:%Y-%m-%d} to {self.end:%Y-%m-%d}"

    def clean(self):
        if self.kind == ProbeSession.Kind.MODULE:
            raise ValidationError({"kind": "module sessions are not scored, so they have no baseline."})
        if self.start and self.end and self.end <= self.start:
            raise ValidationError({"end": "end must be after start."})

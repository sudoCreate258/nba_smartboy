# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ledger records (M5). All three are ProvenancedRecords: one CID each, immutable, exported.

Model validation carries every rule, so a live write (ledger.service) and an import replay
validate the same way. The database refuses UPDATE and DELETE on these tables (migration 0002).
"""
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q

from core.models import ProvenancedRecord
from nymbus import ledger
from nymbus.provenance import canonical_bytes

CATEGORY = RegexValidator(r"^[a-z][a-z0-9_]*$", "A category is lower case letters, digits and underscores.")


class Recipient(models.TextChoices):
    """Simulated recipients only (phase 1). Real parties are an owner gate."""
    SELF_ANALYSIS = "self-analysis", "Self-analysis (simulated)"
    SIM_RESEARCH_PARTNER = "sim-research-partner", "Research partner (simulated)"


assert tuple(Recipient.values) == ledger.RECIPIENTS


class Grant(ProvenancedRecord):
    """Permission for one simulated recipient to read one data category, for a stated purpose.

    Never edited: ending it early is a Revocation; changing it is a revocation plus a new grant.
    """

    record_kind = "grant"

    category = models.CharField(max_length=64, validators=[CATEGORY])
    recipient = models.CharField(max_length=32, choices=Recipient.choices)
    purpose = models.TextField(max_length=500, help_text="Why the recipient may read the data (required).")
    start = models.DateTimeField()
    end = models.DateTimeField(null=True, blank=True, help_text="Optional; the grant ends at this time.")

    class Meta:
        ordering = ["-start"]
        constraints = [
            models.CheckConstraint(condition=Q(end__isnull=True) | Q(end__gt=F("start")), name="grant_end_after_start"),
        ]

    def __str__(self):
        return f"{self.category} -> {self.recipient} ({self.cid[:12]})"

    def clean(self):
        super().clean()
        if isinstance(self.purpose, str) and not self.purpose.strip():
            raise ValidationError({"purpose": "State the purpose."})
        if self.start and self.end and self.end <= self.start:
            raise ValidationError({"end": "end must be after start."})

    def revocation(self):
        return Revocation.objects.filter(grant_cid=self.cid, contributor_id=self.contributor_id).first()

    def is_active(self, at, revocation=None):
        revocation = revocation if revocation is not None else self.revocation()
        return ledger.is_active(self.start, self.end, revocation.at if revocation else None, at)


class Revocation(ProvenancedRecord):
    """Ends a grant from `at` on. Supersedes the grant by reference; the grant itself is kept."""

    record_kind = "revocation"

    grant_cid = models.CharField(max_length=128, unique=True, help_text="CID of the revoked Grant.")
    at = models.DateTimeField()
    reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-at"]

    def __str__(self):
        return f"revokes {self.grant_cid[:12]} ({self.cid[:12]})"

    def clean(self):
        super().clean()
        if not (self.contributor_id and self.grant_cid):
            return
        grant = Grant.objects.filter(cid=self.grant_cid).first()
        if grant is None or grant.contributor_id != self.contributor_id:
            raise ValidationError({"grant_cid": "Must be the CID of a grant of the same contributor."})
        if Revocation.objects.filter(grant_cid=self.grant_cid).exclude(pk=self.pk).exists():
            raise ValidationError({"grant_cid": "This grant is already revoked."})


class AccessEvent(ProvenancedRecord):
    """One simulated read under a grant: which records, when, how many simulated credits.

    Hash chain: `prev_hash` is the SHA-256 of the previous event's canonical bytes (the digest in
    its CID); the first event of a contributor stores 64 zeros.
    """

    record_kind = "access_event"

    seq = models.PositiveIntegerField(validators=[MinValueValidator(1)], help_text="1, 2, ... per contributor.")
    at = models.DateTimeField()
    grant_cid = models.CharField(max_length=128, help_text="CID of the Grant the read was made under.")
    recipient = models.CharField(max_length=32, choices=Recipient.choices)
    category = models.CharField(max_length=64, validators=[CATEGORY])
    purpose = models.TextField(max_length=500)
    record_cids = models.JSONField(blank=True, help_text="CIDs of the records read (may be empty).")
    units = models.PositiveIntegerField(help_text="Simulated credits (one per record read); not money.")
    prev_hash = models.CharField(max_length=64, help_text="SHA-256 hex of the previous event (64 zeros first).")

    class Meta:
        ordering = ["seq"]
        constraints = [
            models.UniqueConstraint(fields=["contributor", "seq"], name="accessevent_one_per_seq"),
            models.UniqueConstraint(fields=["contributor", "prev_hash"], name="accessevent_no_fork"),
        ]

    def __str__(self):
        return f"#{self.seq} {self.category} -> {self.recipient} ({self.cid[:12]})"

    def canonical(self):
        return canonical_bytes(self.record_kind, self.contributor.handle, self.domain_fields())

    def clean(self):
        super().clean()
        cids = self.record_cids
        if not (isinstance(cids, list) and all(isinstance(c, str) and c for c in cids)):
            raise ValidationError({"record_cids": "Must be a list of record CIDs."})
        if len(set(cids)) != len(cids):
            raise ValidationError({"record_cids": "A record is listed twice."})
        if self.units != ledger.units_for(cids):
            raise ValidationError({"units": f"Must be {ledger.units_for(cids)} ({ledger.CREDITS_PER_RECORD} per "
                                            "record read)."})
        if not (self.contributor_id and self.grant_cid and self.at):
            return
        grant = Grant.objects.filter(cid=self.grant_cid, contributor_id=self.contributor_id).first()
        if grant is None:
            raise ValidationError({"grant_cid": "Must be the CID of a grant of the same contributor."})
        for name in ("recipient", "category", "purpose"):
            if getattr(self, name) != getattr(grant, name):
                raise ValidationError({name: f"Must match the grant's {name}."})
        if not grant.is_active(self.at):
            raise ValidationError("The grant was not active at the time of the read.")
        last = AccessEvent.objects.filter(contributor_id=self.contributor_id).exclude(pk=self.pk).order_by("-seq").first()
        expected_seq = last.seq + 1 if last else 1
        expected_prev = ledger.digest(last.canonical()) if last else ledger.GENESIS
        if self.seq != expected_seq:
            raise ValidationError({"seq": f"Must be {expected_seq}, the next in the chain."})
        if self.prev_hash != expected_prev:
            raise ValidationError({"prev_hash": "Must be the SHA-256 of the previous event."})

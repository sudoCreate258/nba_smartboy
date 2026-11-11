from django.db import models

from nymbus.provenance import canonical_bytes, compute_cid


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

    Subclasses set `kind` and implement `domain_fields()`.
    """

    kind = ""

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
        raise NotImplementedError

    def compute_cid(self):
        return compute_cid(
            canonical_bytes(self.kind, self.contributor.handle, self.domain_fields())
        )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError(
                f"{type(self).__name__} {self.cid} is immutable; "
                "create a new record that supersedes it"
            )
        self.cid = self.compute_cid()
        super().save(*args, **kwargs)

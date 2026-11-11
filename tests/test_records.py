import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, models

from core.models import Contributor, ImmutableRecordError, ProvenancedRecord, Supersession


class Dummy(ProvenancedRecord):
    """Concrete stand-in to test the abstract base without a real model."""

    record_kind = "dummy"
    value = models.IntegerField(null=True)

    class Meta:
        app_label = "core"

    def domain_fields(self):
        return {"value": self.value}


@pytest.fixture
def dummy_table(db):
    with connection.schema_editor() as editor:
        editor.create_model(Dummy)
    # No teardown: the test transaction rolls the table back.


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def test_mike_exists_after_migrations(mike):
    assert mike.handle == "mike"


def test_contributor_handle_unique(db):
    with pytest.raises(IntegrityError):
        Contributor.objects.create(handle="mike")


def test_cid_assigned_and_deterministic(dummy_table, mike):
    a = Dummy.objects.create(contributor=mike, value=1)
    assert a.cid.startswith("bafkrei")
    assert a.cid == Dummy(contributor=mike, value=1).compute_cid()


def test_different_content_different_cid(dummy_table, mike):
    a = Dummy.objects.create(contributor=mike, value=1)
    b = Dummy.objects.create(contributor=mike, value=2)
    assert a.cid != b.cid


def test_contributor_changes_cid(dummy_table, mike):
    other = Contributor.objects.create(handle="other")
    assert Dummy(contributor=mike, value=1).compute_cid() != Dummy(
        contributor=other, value=1
    ).compute_cid()


def test_same_content_rejected_by_unique_cid(dummy_table, mike):
    Dummy.objects.create(contributor=mike, value=1)
    with pytest.raises(IntegrityError):
        Dummy.objects.create(contributor=mike, value=1)


def test_saved_record_is_immutable(dummy_table, mike):
    a = Dummy.objects.create(contributor=mike, value=1)
    a.value = 5
    with pytest.raises(ImmutableRecordError):
        a.save()
    assert Dummy.objects.get(pk=a.pk).value == 1


def test_refetched_record_is_immutable(dummy_table, mike):
    Dummy.objects.create(contributor=mike, value=1)
    a = Dummy.objects.get()
    with pytest.raises(ImmutableRecordError):
        a.save()


def test_supersede_chain_and_current(dummy_table, mike):
    a = Dummy.objects.create(contributor=mike, value=1)
    b = Dummy.objects.create(contributor=mike, value=2)
    c = Dummy.objects.create(contributor=mike, value=3)
    d = Dummy.objects.create(contributor=mike, value=9)
    assert set(Dummy.objects.current()) == {a, b, c, d}
    Supersession.record(a, b)
    Supersession.record(b, c)
    assert set(Dummy.objects.current()) == {c, d}


def test_revert_makes_original_current_again(dummy_table, mike):
    a = Dummy.objects.create(contributor=mike, value=1)
    b = Dummy.objects.create(contributor=mike, value=2)
    Supersession.record(a, b)
    Supersession.record(b, a, reason="revert")
    assert set(Dummy.objects.current()) == {a}
    assert Supersession.objects.count() == 2


def test_supersession_is_append_only_and_validated(dummy_table, mike):
    a = Dummy.objects.create(contributor=mike, value=1)
    b = Dummy.objects.create(contributor=mike, value=2)
    s = Supersession.record(a, b)
    s.reason = "x"
    with pytest.raises(ImmutableRecordError):
        s.save()
    with pytest.raises(ImmutableRecordError):
        s.delete()
    with pytest.raises(ImmutableRecordError):
        Supersession.objects.all().update(reason="y")
    with pytest.raises(ImmutableRecordError):
        Supersession.objects.all().delete()
    with pytest.raises(ValidationError):
        Supersession.record(a, a)
    other = Contributor.objects.create(handle="other")
    c = Dummy.objects.create(contributor=other, value=3)
    with pytest.raises(ValidationError):
        Supersession.record(a, c)

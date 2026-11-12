"""M5-T1: data categories come from the module manifests (and the core); one category per kind (R1)."""
import copy

import pytest

from core.services.export import RECORD_MODELS
from ui.modules import CORE, ManifestError, _owners, categories, kinds_of, registry


def test_every_data_kind_has_exactly_one_category():
    found = [k for c in categories() for k in c["kinds"]]
    assert sorted(found) == sorted(m.record_kind for m in RECORD_MODELS)
    assert len(found) == len(set(found))


def test_owners_core_first_then_modules():
    cats = {c["id"]: c for c in categories()}
    assert [c["id"] for c in categories()][:2] == ["daily_metrics", "wellbeing"]
    assert cats["daily_metrics"]["owner"] == CORE and cats["daily_metrics"]["kinds"] == ["daily_snapshot"]
    assert cats["probes"]["owner"] == "probes"
    assert cats["work"] == {**cats["work"], "owner": "zone", "kinds": ["work_block", "reset"]}
    assert cats["training"]["kinds"] == ["training_session", "training_set"]
    assert cats["discomfort"]["label"] == "Discomfort checks"
    assert kinds_of("discomfort") == ["discomfort_check"] and kinds_of("nope") == []


def test_reads_use_the_owners_category():
    for manifest in registry().values():
        for entry in manifest["reads"] + manifest["writes"]:
            assert entry["kind"] in kinds_of(entry["category"]), entry


def test_a_kind_filed_under_two_categories_is_refused():
    reg = copy.deepcopy(registry())
    reg["zone"]["reads"].append({"kind": "probe_session", "category": "work"})
    with pytest.raises(ManifestError, match="probe_session is in category 'probes'"):
        _owners(reg)


def test_a_category_written_by_two_owners_is_refused():
    reg = copy.deepcopy(registry())
    reg["training"]["writes"].append({"kind": "weekly_check", "category": "wellbeing"})
    with pytest.raises(ManifestError, match="already owned by core"):
        _owners(reg)

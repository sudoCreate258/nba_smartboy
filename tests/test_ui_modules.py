"""M4 module registry: manifests, Modules page, a disabled module's UI parts are off (records kept)."""
import datetime
import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import Contributor, DiscomfortCheck
from core.services.export import export_lines
from ui.models import ModuleSetting
from ui.modules import ManifestError, enabled_ids, is_on, owner_of, registry, validate
from ui.today import today
from ui.trends import build

ROOT = Path(__file__).resolve().parent.parent
UTC = datetime.timezone.utc


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


@pytest.fixture
def client_in(client, db):
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    return client


def off(module_id):
    ModuleSetting.objects.update_or_create(module_id=module_id, defaults={"enabled": False})


def test_registry_lists_the_three_first_modules():
    assert list(registry()) == ["probes", "zone", "training"]
    for manifest in registry().values():
        assert manifest["version"] and manifest["compute"]["profile"] == "on-demand"
        assert all({"kind", "category"} <= set(r) for r in manifest["reads"] + manifest["writes"])


def test_every_manifest_file_is_valid_json_and_validates():
    files = sorted((ROOT / "modules").glob("*/module.json"))
    assert len(files) == 3
    for path in files:
        validate(json.loads(path.read_text(encoding="utf-8")), str(path))


@pytest.mark.parametrize("broken", [
    {"id": "x"},
    {"id": "x", "name": "X", "version": "1", "reads": [{"kind": "a"}], "writes": [], "compute": {"profile": "on-demand"},
     "shares": [], "ui": {}},
    {"id": "x", "name": "X", "version": "1", "reads": [], "writes": [], "compute": {"profile": "always"}, "shares": [],
     "ui": {}},
])
def test_invalid_manifests_are_rejected(broken):
    with pytest.raises(ManifestError):
        validate(broken)


def test_ownership_and_defaults(db):
    assert owner_of("checkins", "probe") == "probes" and owner_of("checkins", "work") == "zone"
    assert owner_of("checkins", "snapshot") is None  # core
    assert enabled_ids() == ["probes", "zone", "training"]  # on by default
    off("zone")
    assert enabled_ids() == ["probes", "training"]
    assert not is_on("checkins", "work") and is_on("checkins", "snapshot")


def test_modules_page_toggles(client_in, mike):
    page = client_in.get(reverse("ui:modules")).content.decode()
    assert "Work and zone" in page and "probe_session (probes)" in page and "Turn work and zone off" in page
    resp = client_in.post(reverse("ui:modules"), {"module_id": "zone", "enabled": "0"}, follow=True)
    assert "Work and zone turned off. Its records are kept either way." in resp.content.decode()
    assert ModuleSetting.objects.get(module_id="zone").enabled is False
    client_in.post(reverse("ui:modules"), {"module_id": "zone", "enabled": "1"})
    assert "zone" in enabled_ids()
    assert client_in.post(reverse("ui:modules"), {"module_id": "nope", "enabled": "0"}).status_code == 404


def test_disabled_zone_module_hides_its_ui_but_keeps_records(client_in, mike):
    DiscomfortCheck(contributor=mike, at=datetime.datetime.now(UTC), area="wrist", score=7, trigger="other",
                    sharp_or_numb=True).save()
    off("zone")
    assert client_in.get(reverse("ui:checkin", args=["discomfort"])).status_code == 404
    assert client_in.get(reverse("ui:checkin", args=["snapshot"])).status_code == 200
    index = client_in.get(reverse("ui:checkin_index")).content.decode()
    assert "Work block" not in index and "Daily snapshot" in index
    t = today(mike)
    assert t["zone"] is None
    assert [s["what"] for s in t["stop_signals"]] == ["wrist discomfort, score 7"]  # safety output is core
    assert {c[2] for c in t["checkins"]} == {"snapshot", "probe"}
    groups = {c["group"] for c in build(mike, weeks=4)["charts"]}
    assert "work" not in groups and "discomfort" not in groups and "probes" in groups
    recent = client_in.get(reverse("ui:recent")).content.decode()
    assert "Discomfort check" not in recent
    assert DiscomfortCheck.objects.count() == 1  # the record is kept ...
    assert any('"discomfort_check"' in line for line in export_lines(mike))  # ... and exported


def test_disabled_probes_and_training(client_in, mike):
    off("probes")
    off("training")
    t = today(mike)
    assert t["probes"] == [] and t["zone"] is not None
    assert all(c["group"] != "probes" for c in build(mike, weeks=4)["charts"])
    assert client_in.get(reverse("ui:checkin", args=["probe"])).status_code == 404
    html = client_in.get(reverse("ui:home")).content.decode()
    assert "Probe: puzzle_set" not in html and "Zone (this week)" in html


def test_all_flag_modules_off_points_to_the_modules_page(client_in, mike):
    off("probes")
    off("zone")
    assert "No flag modules are on." in client_in.get(reverse("ui:home")).content.decode()

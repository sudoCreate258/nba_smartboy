# SPDX-License-Identifier: AGPL-3.0-or-later
"""Module registry (M4): every installed Django app with a module.json is a UI module.

A manifest declares what the module reads and writes (record kinds by data
category), its compute profile and what it may share, plus which UI parts it
owns (check-in kinds, home sections, chart groups). In M4 a disabled module's
UI parts are simply off; per-category permission enforcement is M5.
Disabling a module never touches stored records: they stay, with provenance,
and stay in the "my data" export.
"""
import json
from functools import lru_cache
from pathlib import Path

from django.apps import apps

REQUIRED = {"id": str, "name": str, "version": str, "reads": list, "writes": list, "compute": dict, "shares": list,
            "ui": dict}
UI_PARTS = ("checkins", "home", "charts")


class ManifestError(ValueError):
    pass


def validate(manifest, source="module.json"):
    for key, kind in REQUIRED.items():
        if not isinstance(manifest.get(key), kind):
            raise ManifestError(f"{source}: '{key}' must be a {kind.__name__}")
    for key in ("reads", "writes", "shares"):
        for entry in manifest[key]:
            if not (isinstance(entry, dict) and isinstance(entry.get("kind"), str)
                    and isinstance(entry.get("category"), str)):
                raise ManifestError(f"{source}: every '{key}' entry needs 'kind' and 'category'")
    if manifest["compute"].get("profile") not in ("on-demand", "off-hours"):
        raise ManifestError(f"{source}: compute.profile must be 'on-demand' or 'off-hours'")
    for part in UI_PARTS:
        if not isinstance(manifest["ui"].get(part, []), list):
            raise ManifestError(f"{source}: ui.{part} must be a list")
    return manifest


@lru_cache(maxsize=1)
def registry():
    """{module id: manifest} for installed apps that ship a module.json, in INSTALLED_APPS order."""
    out = {}
    for config in apps.get_app_configs():
        path = Path(config.path) / "module.json"
        if path.is_file():
            manifest = validate(json.loads(path.read_text(encoding="utf-8")), str(path))
            if manifest["id"] in out:
                raise ManifestError(f"duplicate module id {manifest['id']!r}")
            out[manifest["id"]] = manifest
    _owners(out)  # refuse inconsistent categories at load time
    return out


# Data categories (M5). A category is owned by whoever writes its record kinds: a module (its
# manifest "writes") or the core, for the kinds no module writes. Every kind has one category.
CORE = "core"
CORE_CATEGORIES = {"daily_snapshot": "daily_metrics", "weekly_check": "wellbeing"}
CATEGORY_LABELS = {
    "daily_metrics": "Daily metrics (sleep, heart rate, body composition)",
    "wellbeing": "Wellbeing (weekly check)",
    "probes": "Cognitive probes",
    "work": "Work blocks and resets",
    "discomfort": "Discomfort checks",
    "training": "Training sessions and sets",
}


def _owners(reg):
    """{category: (owner, [kinds])}, core first; ManifestError when a kind has two categories or a
    category has two owners."""
    kind_category = dict(CORE_CATEGORIES)
    owners = {cat: [CORE, []] for cat in CORE_CATEGORIES.values()}
    for kind, cat in CORE_CATEGORIES.items():
        owners[cat][1].append(kind)
    for mid, manifest in reg.items():
        for key in ("writes", "reads", "shares"):
            for entry in manifest[key]:
                kind, cat = entry["kind"], entry["category"]
                if kind_category.setdefault(kind, cat) != cat:
                    raise ManifestError(f"module {mid}: {kind} is in category {kind_category[kind]!r}, not {cat!r}")
        for entry in manifest["writes"]:
            owner, kinds = owners.setdefault(entry["category"], [mid, []])
            if owner != mid:
                raise ManifestError(f"module {mid}: category {entry['category']!r} is already owned by {owner}")
            if entry["kind"] not in kinds:
                kinds.append(entry["kind"])
    return {cat: (owner, kinds) for cat, (owner, kinds) in owners.items()}


def categories():
    """[{"id", "label", "owner", "kinds"}] for every data category, core first, then modules in order."""
    return [{"id": cat, "label": CATEGORY_LABELS.get(cat, cat.replace("_", " ").capitalize()), "owner": owner,
             "kinds": list(kinds)} for cat, (owner, kinds) in _owners(registry()).items()]


def kinds_of(category):
    """Record kinds of a category ([] for an unknown one)."""
    return next((c["kinds"] for c in categories() if c["id"] == category), [])


def enabled_ids():
    """Ids of enabled modules (a module with no stored setting is enabled)."""
    from .models import ModuleSetting

    off = set(ModuleSetting.objects.filter(enabled=False).values_list("module_id", flat=True))
    return [mid for mid in registry() if mid not in off]


def owner_of(part, name):
    """Module id that owns a UI part (e.g. ("checkins", "probe")), or None for core parts."""
    for mid, manifest in registry().items():
        if name in manifest["ui"].get(part, []):
            return mid
    return None


def is_on(part, name, enabled=None):
    """True for core parts and for parts of enabled modules."""
    owner = owner_of(part, name)
    return owner is None or owner in (enabled if enabled is not None else enabled_ids())

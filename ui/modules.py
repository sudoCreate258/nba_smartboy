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
    return out


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

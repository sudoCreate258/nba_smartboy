# SPDX-License-Identifier: AGPL-3.0-or-later
from django.apps import AppConfig


class TrainingModuleConfig(AppConfig):
    """UI module 'training' (manifest: module.json next to this file)."""

    name = "modules.training"
    label = "module_training"

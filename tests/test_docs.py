"""003 internal docs: DATA_MODEL.md is generated from the models and must not go stale."""
from io import StringIO
from pathlib import Path

from django.core.management import call_command

ROOT = Path(__file__).resolve().parent.parent


def test_data_model_doc_is_up_to_date():
    out = StringIO()
    call_command("data_model_doc", "--check", stdout=out)
    assert "up to date" in out.getvalue()


def test_data_model_doc_covers_every_record_and_omit_if_null_field():
    from django.apps import apps

    from core.models import ProvenancedRecord

    text = (ROOT / "docs" / "DATA_MODEL.md").read_text(encoding="utf-8")
    # Models defined in core/models.py (tests may register throwaway subclasses).
    records = [m for m in apps.get_app_config("core").get_models()
               if issubclass(m, ProvenancedRecord) and m.__module__ == "core.models"]
    assert len(records) == 8
    for model in records:
        assert f"### {model.__name__} (`{model.record_kind}`)" in text, model.__name__
    assert "| `move_time_cv` |" in text and "OMIT_IF_NULL" in text


def test_internal_docs_exist_and_mark_planned_work():
    for name in ("ARCHITECTURE.md", "DATA_MODEL.md", "OPERATIONS.md"):
        assert (ROOT / "docs" / name).is_file(), name
    arch = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "planned (M6)" in arch and "planned (M7)" in arch  # not-yet-built work stays marked
    assert "after M5" in arch and "Simulated (M5)" in arch  # and what is built is described as built

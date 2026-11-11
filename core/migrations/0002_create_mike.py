from django.db import migrations


def create_mike(apps, schema_editor):
    Contributor = apps.get_model("core", "Contributor")
    Contributor.objects.get_or_create(handle="mike")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_mike, migrations.RunPython.noop),
    ]

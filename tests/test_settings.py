import pytest
from django.conf import settings
from django.db import connection


def test_timezone_is_owner_timezone():
    assert settings.TIME_ZONE == "America/New_York"
    assert settings.USE_TZ is True


@pytest.mark.django_db
def test_database_is_postgres_16():
    assert connection.vendor == "postgresql"
    assert connection.pg_version // 10000 == 16

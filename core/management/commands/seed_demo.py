# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic DEMO profile (MVP, 025 R2): contributor `demo` with 14 days of sleep, body composition,
cognitive probes and training, one correction and a small consent/read history.

Every value is made up and every record says DEMO in its notes. Fixed dates and values, so the
same records (same CIDs) come out every time: running it again adds nothing.
"""
import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Contributor, DailySnapshot, ProbeSession, TrainingSession, TrainingSet
from core.services.records import save_record
from core.services.snapshots import CREATED
from ledger import service
from ledger.models import Grant

HANDLE = "demo"
NOTE = "DEMO (synthetic, not a real person)"
FIRST_DAY = datetime.date(2026, 11, 1)
DAYS = 14


def _local(day, hour, minute, tz):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=tz)


def seed(stdout=None):
    """Create what is missing; returns the number of records created."""
    created = 0
    with transaction.atomic():
        demo, _ = Contributor.objects.get_or_create(handle=HANDLE, defaults={"timezone": "America/New_York"})
        tz = demo.tzinfo

        def add(record, **kw):
            nonlocal created
            saved, outcome = save_record(record, **kw)
            created += outcome == CREATED
            return saved

        for i in range(DAYS):
            day = FIRST_DAY + datetime.timedelta(days=i)
            # A snapshot that exists (perhaps corrected) is left alone: re-adding the original would revert it.
            if not DailySnapshot.objects.filter(contributor=demo, date=day).exists():
                add(DailySnapshot(contributor=demo, date=day, source=DailySnapshot.Source.MANUAL,
                                  sleep_score=70 + (i * 7) % 20, wake_time=_local(day, 6, 30, tz),
                                  sleep_duration_min=390 + (i * 13) % 80, resting_hr_sleep=52 + i % 5,
                                  hrv=55 + (i * 3) % 15, weight_kg=f"{78.0 - i * 0.1:.1f}",
                                  body_fat_pct=f"{18.0 - i * 0.05:.1f}",
                                  bia_timing=DailySnapshot.BiaTiming.PRE_SESSION, notes=NOTE))
            add(ProbeSession(contributor=demo, started_at=_local(day, 8, 0, tz), kind=ProbeSession.Kind.PUZZLE_SET,
                             n_items=10, accuracy_pct=f"{70 + (i * 11) % 25}.0", median_solve_s=f"{20 + (i * 5) % 12}.0",
                             blunders=i % 3, notes=NOTE))
            if i % 2 == 0:
                session = add(TrainingSession(contributor=demo, started_at=_local(day, 18, 0, tz), program="DEMO plan",
                                              meso_week=1 + i // 7, session_rpe="7.5", notes=NOTE))
                for order, (exercise, group, load) in enumerate(
                        [("bench press", "chest", 60 + i), ("row", "back", 55 + i), ("squat", "quads", 80 + i)], 1):
                    add(TrainingSet(contributor=demo, session_cid=session.cid, order=order, exercise=exercise,
                                    muscle_group=group, load_kg=str(load), reps=8, rir=2, notes=NOTE))

        # One correction, so the provenance page has a chain to show: day 3's sleep score was mistyped.
        day3 = FIRST_DAY + datetime.timedelta(days=2)
        old = DailySnapshot.objects.current().filter(contributor=demo, date=day3).first()
        if old is not None and old.sleep_score != 88:
            fixed = DailySnapshot(contributor=demo, date=day3, source=old.source, sleep_score=88, wake_time=old.wake_time,
                                  sleep_duration_min=old.sleep_duration_min, resting_hr_sleep=old.resting_hr_sleep,
                                  hrv=old.hrv, weight_kg=old.weight_kg, body_fat_pct=old.body_fat_pct,
                                  bia_timing=old.bia_timing, notes=NOTE + "; corrected sleep score")
            fixed.save(supersede=True, reason="DEMO: mistyped sleep score")  # the snapshot write path, with a reason
            created += 1

        # Consent history: a simulated research partner may read the probes for a week, reads twice, is revoked.
        if not Grant.objects.filter(contributor=demo).exists():
            start = _local(FIRST_DAY + datetime.timedelta(days=DAYS), 9, 0, tz)
            g = service.grant(demo, "probes", "sim-research-partner", "DEMO: fatigue study", now=start)
            service.simulated_read(demo, "sim-research-partner", "probes", now=start + datetime.timedelta(hours=1))
            service.simulated_read(demo, "sim-research-partner", "probes", now=start + datetime.timedelta(days=1))
            service.revoke(demo, g.cid, reason="DEMO: study over", now=start + datetime.timedelta(days=2))
    return created


class Command(BaseCommand):
    help = "Create the synthetic DEMO profile (contributor 'demo', 14 days). Idempotent."

    def handle(self, *args, **options):
        n = seed()
        self.stdout.write(f"DEMO profile '{HANDLE}': {n} records created" + (" (already complete)" if n == 0 else "")
                          + ". Synthetic data only.")

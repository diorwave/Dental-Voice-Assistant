"""Test doubles for external services."""
import itertools
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def clinic_time(*args) -> datetime:
    return datetime(*args, tzinfo=NY)


class _Request:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class FakeEvents:
    def __init__(self, calendar):
        self._calendar = calendar

    def list(self, **kwargs):
        return _Request(lambda: {"items": list(self._calendar.items)})

    def insert(self, calendarId, body):
        def _insert():
            if self._calendar.fail_insert:
                raise RuntimeError("calendar unavailable")
            event = dict(body, id=f"evt{next(self._calendar.ids)}")
            self._calendar.items.append(event)
            self._calendar.inserted.append(event)
            return event

        return _Request(_insert)


class FakeCalendar:
    """Minimal stand-in for the googleapiclient Calendar v3 service."""

    def __init__(self, items=None):
        self.items = list(items or [])
        self.inserted = []
        self.fail_insert = False
        self.ids = itertools.count(1)

    def events(self):
        return FakeEvents(self)

    def add_timed(self, start: datetime, end: datetime, **extra):
        self.items.append({"start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}, **extra})

    def add_all_day(self, day: str, end_day: str):
        self.items.append({"start": {"date": day}, "end": {"date": end_day}})


def patch_calendar(fake: FakeCalendar):
    return mock.patch("calls.services.calendar.get_calendar_service", return_value=fake)


def patch_now(dt: datetime):
    return mock.patch("calls.clinic.now", return_value=dt)


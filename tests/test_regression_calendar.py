"""Regression tests — one per real bug this plugin hit.

Each test fails if the fix is reverted, and names the bug it pins.
"""

import datetime
import importlib.machinery
import importlib.util
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))     # so make_store is importable either way
CLI = ROOT / "bin/omarchy-calendar"

_loader = importlib.machinery.SourceFileLoader("omarchy_calendar_reg", str(CLI))
_spec = importlib.util.spec_from_loader("omarchy_calendar_reg", _loader)
cal = importlib.util.module_from_spec(_spec)
_loader.exec_module(cal)

USECS = 1000000


class ProfileSelectionRegression(unittest.TestCase):
    """BUG: the profile finder picked the profile flagged Default=1 (an older,
    unused profile) instead of the profile Thunderbird actually runs.

    Reality: Thunderbird installs a profile as "…default-release" and records it in
    an [Install…] section; a stale Profile with Default=1 must NOT win.
    """

    def test_install_default_beats_profile_default_flag(self):
        with tempfile.TemporaryDirectory() as d:
            base = pathlib.Path(d) / "thunderbird"
            base.mkdir()
            (base / "profiles.ini").write_text(
                "[Profile0]\nPath=old.default\nIsRelative=1\nDefault=1\n"
                "[Profile1]\nPath=inuse.default-release\nIsRelative=1\n"
                "[InstallABC]\nDefault=inuse.default-release\nLocked=1\n")
            (base / "old.default").mkdir()
            (base / "inuse.default-release").mkdir()
            self.assertEqual(cal._profile_from_ini(base / "profiles.ini", base).name,
                             "inuse.default-release")


class SameDirCopyRegression(unittest.TestCase):
    """BUG: reading a store whose parent was also the workdir raised
    shutil.SameFileError and aborted the whole scan.
    """

    def test_reading_store_in_place_does_not_copy_onto_itself(self):
        from test_unit_calendar import make_store
        with tempfile.TemporaryDirectory() as d:
            db = pathlib.Path(d) / "local.sqlite"
            start = int(datetime.datetime(2026, 1, 1, 9).timestamp()) * USECS
            make_store(db, rows=[("c", "e", "X", start, start + USECS, None, 0, "UTC", None)])
            events = cal.load_events(db, d, "c")     # workdir == parent
            self.assertEqual(len(events), 1)


class UntilDateRegression(unittest.TestCase):
    """BUG: a DATE-valued UNTIL (YYYYMMDD) was compared as midnight, so the final
    day of a series was dropped (a 09:00 event on the UNTIL day fell after 00:00).
    """

    def test_date_until_includes_the_whole_final_day(self):
        start = datetime.datetime(2026, 1, 1, 9, 0)
        occ = cal.expand_occurrences(start, {"FREQ": "DAILY", "UNTIL": "20260103"},
                                     datetime.datetime(2026, 3, 1))
        self.assertEqual([o.day for o in occ], [1, 2, 3])

    def test_datetime_until_still_compares_instants(self):
        start = datetime.datetime(2026, 1, 1, 9, 0)
        occ = cal.expand_occurrences(
            start, {"FREQ": "DAILY", "UNTIL": "20260103T040000Z"},
            datetime.datetime(2026, 3, 1))
        # 04:00Z is well before the local 09:00 occurrence on the 3rd, so it is
        # excluded — a DATE-TIME UNTIL is an instant, unlike a bare DATE.
        self.assertEqual([o.day for o in occ], [1, 2])


class StoreBindingRegression(unittest.TestCase):
    """BUG: the local storage calendar's file is named ``local.sqlite`` while its
    registry id is a UUID, so discovery invented a phantom "local" calendar and left
    the real one with no store.
    """

    def test_local_sqlite_binds_to_registered_storage_calendar(self):
        from test_unit_calendar import make_store
        with tempfile.TemporaryDirectory() as d:
            profile = pathlib.Path(d)
            (profile / "calendar-data").mkdir()
            (profile / "prefs.js").write_text(
                'user_pref("calendar.registry.uuid-home.name", "Home");\n'
                'user_pref("calendar.registry.uuid-home.type", "storage");\n')
            make_store(profile / "calendar-data" / "local.sqlite")
            cals = cal.calendars_of(profile)
            self.assertEqual([c["name"] for c in cals], ["Home"])
            self.assertEqual(cals[0]["store"].name, "local.sqlite")


class DedupeRegression(unittest.TestCase):
    """BUG: event identity included the calendar, so the same event copied into the
    default never deduplicated against its copy elsewhere.
    """

    def test_same_event_in_two_calendars_dedupes(self):
        events = [
            {"calendar": "home", "id": "e1", "title": "d", "start_usecs": USECS, "end_usecs": 2 * USECS},
            {"calendar": "work", "id": "e1", "title": "w", "start_usecs": USECS, "end_usecs": 2 * USECS},
        ]
        merged = cal.merge_events(events, "home")
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["title"], "d")


if __name__ == "__main__":
    unittest.main()

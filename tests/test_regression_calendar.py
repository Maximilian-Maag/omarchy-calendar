"""Regression tests — one per real bug this plugin hit.

Each test fails if the fix is reverted, and names the bug it pins.
"""

import datetime
import importlib.machinery
import importlib.util
import pathlib
import sqlite3
import subprocess
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


class ExpansionWindowRegression(unittest.TestCase):
    """BUG (#7): expansion started at the master DTSTART and stopped at
    MAX_OCCURRENCES, so for a long-running series the cap was spent years before the
    query window and every recent/upcoming occurrence was silently dropped.
    """

    def _event(self, now, freq, age, ahead_days=7, **rule):
        us = int(age.timestamp()) * USECS
        return {"id": "e", "calendar": "c", "title": "series", "start_usecs": us,
                "end_usecs": us + 3600 * USECS, "status": "", "allday": False,
                "floating": False, "rule": {"FREQ": freq, **rule},
                "exdate": set(), "rdate": [], "exceptions": set()}

    def test_long_running_daily_series_has_an_occurrence_in_the_next_7_days(self):
        now = datetime.datetime(2026, 11, 15, 12, 0)
        event = self._event(now, "DAILY", now - datetime.timedelta(days=1095))
        horizon = now + datetime.timedelta(days=7)
        occ = cal.occurrences_of(event, horizon, window_start=now)
        self.assertTrue(occ, "a 3-year-old daily series dropped every upcoming occurrence")
        self.assertTrue(any(now <= s <= horizon for s, _ in occ))
        self.assertTrue(cal.upcoming([event], now=now, days=7))

    def test_long_running_weekly_series_has_an_occurrence_in_the_next_7_days(self):
        now = datetime.datetime(2026, 11, 15, 12, 0)
        event = self._event(now, "WEEKLY", now - datetime.timedelta(weeks=700))
        horizon = now + datetime.timedelta(days=7)
        occ = cal.occurrences_of(event, horizon, window_start=now)
        self.assertTrue(occ)
        self.assertTrue(any(now <= s <= horizon for s, _ in occ))

    def test_long_running_monthly_series_has_an_occurrence_in_the_next_month(self):
        now = datetime.datetime(2026, 11, 15, 12, 0)
        event = self._event(now, "MONTHLY", now - datetime.timedelta(days=365 * 600))
        horizon = now + datetime.timedelta(days=40)
        occ = cal.occurrences_of(event, horizon, window_start=now)
        self.assertTrue(occ)
        self.assertTrue(any(now <= s <= horizon for s, _ in occ))

    def test_long_running_yearly_series_has_an_occurrence_in_the_next_year(self):
        now = datetime.datetime(2026, 11, 15, 12, 0)
        event = self._event(now, "YEARLY", now - datetime.timedelta(days=365 * 600))
        horizon = now + datetime.timedelta(days=400)
        occ = cal.occurrences_of(event, horizon, window_start=now)
        self.assertTrue(occ)
        self.assertTrue(any(now <= s <= horizon for s, _ in occ))

    def test_bounded_count_series_is_still_expanded_from_its_start(self):
        # a COUNT-bounded series must keep its own first occurrences: the window jump
        # only applies to unbounded series.
        start = datetime.datetime(2026, 1, 1, 9, 0)
        occ = cal.expand_occurrences(start, {"FREQ": "DAILY", "COUNT": "3"},
                                     datetime.datetime(2026, 6, 1),
                                     window_start=datetime.datetime(2026, 5, 1))
        self.assertEqual([o.day for o in occ], [1, 2, 3])


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



class CombineApplyRegression(unittest.TestCase):
    """BUG: `combine --apply` printed the plan and returned 0 but wrote nothing —
    the store was byte-identical afterwards (a silent no-op behind a --apply flag).
    """

    def test_combine_apply_writes_into_the_default_store(self):
        import sys
        sys.path.insert(0, str(ROOT / "tests"))
        from test_unit_calendar import make_full_store
        with tempfile.TemporaryDirectory() as d:
            profile = pathlib.Path(d) / "profile"
            (profile / "calendar-data").mkdir(parents=True)
            (profile / "prefs.js").write_text(
                'user_pref("calendar.registry.uuid-home.name", "Home");\n'
                'user_pref("calendar.registry.uuid-home.type", "storage");\n'
                'user_pref("calendar.registry.uuid-work.name", "Work");\n'
                'user_pref("calendar.registry.uuid-work.type", "caldav");\n')
            make_full_store(profile / "calendar-data" / "local.sqlite", "uuid-home",
                            [("h1", "Home event")])
            make_full_store(profile / "calendar-data" / "uuid-work.sqlite", "uuid-work",
                            [("w1", "Work event")])
            cfg = pathlib.Path(d) / "calendar.json"
            cfg.write_text('{"default_calendar": "uuid-home"}')
            r = subprocess.run([sys.executable, str(CLI), "--profile", str(profile),
                                "--config", str(cfg), "--force", "combine", "--apply"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("combined 1 event", r.stdout)
            conn = sqlite3.connect(str(profile / "calendar-data" / "local.sqlite"))
            try:
                titles = [row[0] for row in conn.execute(
                    "SELECT title FROM cal_events ORDER BY title")]
            finally:
                conn.close()
            self.assertEqual(titles, ["Home event", "Work event"])


class DefaultConfigRegression(unittest.TestCase):
    """BUG: `default <name>` saved the whole merged config, baking the shipped defaults
    (aggregate, combine) into the user's file so a later shipped change was overridden.
    """

    def test_default_persists_only_the_override(self):
        import sys, json
        sys.path.insert(0, str(ROOT / "tests"))
        from test_unit_calendar import make_full_store
        with tempfile.TemporaryDirectory() as d:
            profile = pathlib.Path(d) / "profile"
            (profile / "calendar-data").mkdir(parents=True)
            (profile / "prefs.js").write_text(
                'user_pref("calendar.registry.uuid-home.name", "Home");\n'
                'user_pref("calendar.registry.uuid-home.type", "storage");\n')
            make_full_store(profile / "calendar-data" / "local.sqlite", "uuid-home", [])
            cfg = pathlib.Path(d) / "calendar.json"
            subprocess.run([sys.executable, str(CLI), "--profile", str(profile),
                            "--config", str(cfg), "default", "Home"],
                           capture_output=True, text=True)
            self.assertEqual(json.loads(cfg.read_text()), {"default_calendar": "uuid-home"})


class DisabledCalendarGateRegression(unittest.TestCase):
    """BUG: `list` skipped a disabled non-default calendar but `combine` still mined
    it for events to copy into the default, and `promote` still wrote INTO it — the
    `disabled` gate was honoured in one command and missed in the other two.
    """

    def _profile(self, d):
        from test_unit_calendar import make_full_store
        profile = pathlib.Path(d) / "profile"
        (profile / "calendar-data").mkdir(parents=True)
        (profile / "prefs.js").write_text(
            'user_pref("calendar.registry.uuid-home.name", "Home");\n'
            'user_pref("calendar.registry.uuid-home.type", "storage");\n'
            'user_pref("calendar.registry.uuid-work.name", "Work");\n'
            'user_pref("calendar.registry.uuid-work.type", "caldav");\n'
            'user_pref("calendar.registry.uuid-arch.name", "Archive");\n'
            'user_pref("calendar.registry.uuid-arch.type", "storage");\n'
            'user_pref("calendar.registry.uuid-arch.disabled", true);\n')
        make_full_store(profile / "calendar-data" / "local.sqlite", "uuid-home",
                        [("h1", "Home event")])
        make_full_store(profile / "calendar-data" / "uuid-work.sqlite", "uuid-work",
                        [("w1", "Work event")])
        make_full_store(profile / "calendar-data" / "uuid-arch.sqlite", "uuid-arch",
                        [("a1", "ARCHIVED event")])
        cfg = pathlib.Path(d) / "calendar.json"
        cfg.write_text('{"default_calendar": "uuid-home"}')
        return profile, cfg

    def _run(self, profile, cfg, *args):
        return subprocess.run([sys.executable, str(CLI), "--profile", str(profile),
                               "--config", str(cfg), "--force", *args],
                              capture_output=True, text=True)

    def _titles(self, path):
        conn = sqlite3.connect(str(path))
        try:
            return [row[0] for row in conn.execute("SELECT title FROM cal_events ORDER BY title")]
        finally:
            conn.close()

    def test_combine_does_not_mine_disabled_calendar(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            profile, cfg = self._profile(d)
            r = self._run(profile, cfg, "combine", "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            cals = [a["calendar"] for a in json.loads(r.stdout)["additions"]]
            self.assertIn("uuid-work", cals)
            self.assertNotIn("uuid-arch", cals)

    def test_combine_apply_does_not_copy_disabled_events(self):
        with tempfile.TemporaryDirectory() as d:
            profile, cfg = self._profile(d)
            r = self._run(profile, cfg, "combine", "--apply")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self._titles(profile / "calendar-data" / "local.sqlite"),
                             ["Home event", "Work event"])

    def test_promote_does_not_target_disabled_calendar(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            profile, cfg = self._profile(d)
            r = self._run(profile, cfg, "promote", "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            targets = [w["target"] for w in json.loads(r.stdout)["writes"]]
            self.assertIn("uuid-work", targets)
            self.assertNotIn("uuid-arch", targets)

    def test_promote_apply_does_not_write_into_disabled_calendar(self):
        with tempfile.TemporaryDirectory() as d:
            profile, cfg = self._profile(d)
            r = self._run(profile, cfg, "promote", "--apply")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self._titles(profile / "calendar-data" / "uuid-arch.sqlite"),
                             ["ARCHIVED event"])

    def test_include_disabled_opt_in_restores_the_calendar(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            profile, cfg = self._profile(d)
            r = self._run(profile, cfg, "combine", "--json", "--include-disabled")
            self.assertEqual(r.returncode, 0, r.stderr)
            cals = [a["calendar"] for a in json.loads(r.stdout)["additions"]]
            self.assertIn("uuid-arch", cals)


class PutEventsTbStoreRegression(unittest.TestCase):
    """BUG: `put_events` only wrote events carrying a raw ``ics`` body, so a
    Thunderbird-store-sourced addition was silently dropped from ``combine --apply``
    into a Nextcloud default — the plan printed and the command exited 0.
    """

    def test_tb_store_event_is_written_with_a_synthesised_body(self):
        nc = {"base_url": "https://nc.example", "user": "u", "principal": "p",
              "password": "secret"}
        calcon = {"id": "nc:work", "uri": "/remote.php/dav/calendars/u/work/"}
        tb_event = {"id": "work-1", "calendar": "uuid-work", "title": "Work event",
                    "start_usecs": 1000 * USECS, "end_usecs": 2000 * USECS,
                    "allday": False, "floating": False}   # TB shape: no 'ics'
        calls = []

        def fake(nc_, uri, uid, ics, **kw):
            calls.append((uid, ics))
            return bool(ics)

        orig = cal.dav_put_event
        cal.dav_put_event = fake
        try:
            written = cal.put_events({"nextcloud": nc}, calcon, [tb_event])
        finally:
            cal.dav_put_event = orig
        self.assertEqual(written, 1)
        self.assertEqual(calls[0][0], "work-1")
        self.assertTrue(calls[0][1])                       # a body was built, not None
        self.assertIn("BEGIN:VEVENT", calls[0][1])
        self.assertIn("SUMMARY:Work event", calls[0][1])

    def test_event_ics_round_trips_through_the_parser(self):
        event = {"id": "u9", "calendar": "c", "title": "Round trip",
                 "start_usecs": 4000000 * USECS, "end_usecs": 5000000 * USECS,
                 "allday": False, "floating": False}
        parsed = cal._events_from_ics(cal.event_ics(event), "c")
        self.assertEqual(parsed[0]["id"], "u9")
        self.assertEqual(parsed[0]["title"], "Round trip")


class MalformedDtendRegression(unittest.TestCase):
    """BUG (#8): _events_from_ics unpacked DTEND unconditionally, so an empty,
    unparsable or out-of-range DTEND in a fetched calendar raised through
    nextcloud_events into cmd_list/cmd_combine and killed the whole command,
    instead of skipping the one bad event as the DTSTART path already did.
    """

    def _ics(self, dtend):
        return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
                "UID:u1\r\nSUMMARY:Bad\r\nDTSTART:20260605T090000Z\r\n"
                "DTEND:%s\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n" % dtend)

    def test_empty_dtend_skips_the_event(self):
        self.assertEqual(cal._events_from_ics(self._ics(""), "c"), [])

    def test_unparsable_dtend_skips_the_event(self):
        self.assertEqual(cal._events_from_ics(self._ics("not-a-date"), "c"), [])

    def test_out_of_range_dtend_skips_the_event(self):
        self.assertEqual(cal._events_from_ics(self._ics("20261301T000000Z"), "c"), [])

    def test_valid_dtend_still_parses(self):
        evs = cal._events_from_ics(self._ics("20260605T100000Z"), "c")
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["end_usecs"] - evs[0]["start_usecs"], 3600 * USECS)


if __name__ == "__main__":
    unittest.main()

"""Unit tests for omarchy-calendar's pure logic.

The shipped CLI has no ``.py`` extension (it is installed as ``omarchy-calendar``),
so it is loaded with a SourceFileLoader rather than imported by name.
"""

import contextlib
import datetime
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import sqlite3
import tempfile
import time
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = ROOT / "bin/omarchy-calendar"

_loader = importlib.machinery.SourceFileLoader("omarchy_calendar", str(CLI))
_spec = importlib.util.spec_from_loader("omarchy_calendar", _loader)
cal = importlib.util.module_from_spec(_spec)
_loader.exec_module(cal)

USECS = 1000000


@contextlib.contextmanager
def non_utc_zone():
    """Run the block with a non-UTC local zone, restoring it afterwards.

    The UTC-vs-local conversion tests only bite when local time is not UTC; on a
    UTC CI runner their assertions hold no matter which branch runs, so a mutant
    would survive. Pinning a real zone keeps the suite equally strict everywhere.
    """
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Berlin"
    time.tzset()
    try:
        yield
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()


def make_store(path, rows=(), recurrence=()):
    """Create a Thunderbird-shaped calendar store at `path`."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE cal_events (cal_id TEXT, id TEXT, time_created INTEGER, "
        "last_modified INTEGER, title TEXT, priority INTEGER, privacy TEXT, "
        "ical_status TEXT, flags INTEGER, event_start INTEGER, event_end INTEGER, "
        "event_stamp INTEGER, event_start_tz TEXT, event_end_tz TEXT, "
        "recurrence_id INTEGER, recurrence_id_tz TEXT, alarm_last_ack INTEGER, "
        "offline_journal INTEGER)")
    conn.execute("CREATE TABLE cal_recurrence (item_id TEXT, cal_id TEXT, icalString TEXT)")
    for row in rows:
        conn.execute(
            "INSERT INTO cal_events (cal_id, id, title, event_start, event_end, "
            "ical_status, flags, event_start_tz, recurrence_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)", row)
    for item_id, ical in recurrence:
        conn.execute("INSERT INTO cal_recurrence (item_id, icalString) VALUES (?,?)",
                     (item_id, ical))
    conn.commit()
    conn.close()


class TimeTests(unittest.TestCase):
    def test_usecs_to_epoch(self):
        self.assertEqual(cal.usecs_to_epoch(1700000000000000), 1700000000)

    def test_to_display_zoned_is_local(self):
        # 2026-01-01T00:00:00Z as microseconds
        us = int(datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc).timestamp()) * USECS
        self.assertEqual(cal.to_display(us).year, 2026)

    def test_to_display_allday_is_not_shifted(self):
        # midnight UTC stored for an all-day date must read back as midnight
        us = int(datetime.datetime(2026, 6, 5, tzinfo=datetime.timezone.utc).timestamp()) * USECS
        shown = cal.to_display(us, allday=True)
        self.assertEqual((shown.hour, shown.minute, shown.day), (0, 0, 5))

    def test_to_display_defaults_to_zoned_conversion(self):
        # the allday/floating defaults are False: with neither flag set a stored
        # instant is converted to local time, NOT read back as UTC wall clock.
        # That only differs from the allday branch when local time is not UTC, so
        # pin a non-UTC zone — otherwise this passes trivially on a UTC runner.
        with non_utc_zone():
            us = int(datetime.datetime(2026, 6, 5, 12, tzinfo=datetime.timezone.utc).timestamp()) * USECS
            self.assertEqual(cal.to_display(us),
                             datetime.datetime.fromtimestamp(us // USECS))
            self.assertNotEqual(cal.to_display(us),
                                cal.to_display(us, allday=True))


class RuleTests(unittest.TestCase):
    def test_parse_rrule(self):
        rule = cal.parse_rrule("BEGIN:VEVENT\r\nRRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE\r\nEND")
        self.assertEqual(rule["FREQ"], "WEEKLY")
        self.assertEqual(rule["INTERVAL"], "2")
        self.assertEqual(rule["BYDAY"], "MO,WE")

    def test_parse_rrule_none(self):
        self.assertIsNone(cal.parse_rrule("SUMMARY:hi"))

    def test_parse_until_forms(self):
        self.assertEqual(cal.parse_until("20260605"), datetime.datetime(2026, 6, 5))
        self.assertEqual(cal.parse_until("20260605T090000Z"),
                         datetime.datetime(2026, 6, 5, 9, 0, 0))
        self.assertIsNone(cal.parse_until("nonsense"))

    def test_daily_with_count(self):
        start = datetime.datetime(2026, 1, 1, 9, 0)
        occ = cal.expand_occurrences(start, {"FREQ": "DAILY", "COUNT": "3"},
                                     datetime.datetime(2026, 3, 1))
        self.assertEqual(occ, [datetime.datetime(2026, 1, 1, 9),
                               datetime.datetime(2026, 1, 2, 9),
                               datetime.datetime(2026, 1, 3, 9)])

    def test_daily_interval(self):
        start = datetime.datetime(2026, 1, 1, 9, 0)
        occ = cal.expand_occurrences(start, {"FREQ": "DAILY", "INTERVAL": "2", "COUNT": "3"},
                                     datetime.datetime(2026, 3, 1))
        self.assertEqual([o.day for o in occ], [1, 3, 5])

    def test_weekly_byday(self):
        start = datetime.datetime(2026, 1, 5, 9, 0)   # a Monday
        occ = cal.expand_occurrences(start, {"FREQ": "WEEKLY", "BYDAY": "MO,WE", "COUNT": "4"},
                                     datetime.datetime(2026, 3, 1))
        self.assertEqual([(o.month, o.day) for o in occ],
                         [(1, 5), (1, 7), (1, 12), (1, 14)])

    def test_monthly_keeps_time_of_day(self):
        start = datetime.datetime(2026, 1, 15, 14, 30)
        occ = cal.expand_occurrences(start, {"FREQ": "MONTHLY", "COUNT": "3"},
                                     datetime.datetime(2026, 6, 1))
        self.assertEqual([o.hour for o in occ], [14, 14, 14])
        self.assertEqual([o.day for o in occ], [15, 15, 15])

    def test_monthly_bymonthday_skips_missing(self):
        start = datetime.datetime(2026, 1, 31, 9, 0)
        occ = cal.expand_occurrences(start, {"FREQ": "MONTHLY", "COUNT": "3"},
                                     datetime.datetime(2026, 12, 1))
        # February has no 31st, so it is skipped, not shifted to March 3rd.
        self.assertEqual([o.month for o in occ[:3]], [1, 3, 5])

    def test_monthly_byday_ordinal(self):
        # FREQ=MONTHLY;BYDAY=2TU -> the SECOND Tuesday, not the master's day-of-month.
        start = datetime.datetime(2026, 1, 6, 9, 0)   # a Tuesday
        occ = cal.expand_occurrences(start, {"FREQ": "MONTHLY", "BYDAY": "2TU"},
                                     datetime.datetime(2026, 6, 1))
        self.assertEqual([(o.month, o.day, o.strftime("%a")) for o in occ],
                         [(1, 13, "Tue"), (2, 10, "Tue"), (3, 10, "Tue"),
                          (4, 14, "Tue"), (5, 12, "Tue")])

    def test_monthly_byday_first_ordinal(self):
        start = datetime.datetime(2026, 1, 6, 9, 0)   # the first Tuesday of Jan 2026
        occ = cal.expand_occurrences(start, {"FREQ": "MONTHLY", "BYDAY": "1TU", "COUNT": "3"},
                                     datetime.datetime(2026, 12, 1))
        self.assertEqual([(o.month, o.day, o.strftime("%a")) for o in occ],
                         [(1, 6, "Tue"), (2, 3, "Tue"), (3, 3, "Tue")])

    def test_monthly_byday_negative_ordinal_is_last(self):
        # BYDAY=-1FR -> the LAST Friday of the month.
        start = datetime.datetime(2026, 1, 2, 9, 0)   # a Friday
        occ = cal.expand_occurrences(start, {"FREQ": "MONTHLY", "BYDAY": "-1FR"},
                                     datetime.datetime(2026, 4, 1))
        self.assertEqual([(o.month, o.day, o.strftime("%a")) for o in occ],
                         [(1, 30, "Fri"), (2, 27, "Fri"), (3, 27, "Fri")])

    def test_monthly_byday_plain_weekday_is_every_one(self):
        # BYDAY=TU without an ordinal -> EVERY Tuesday of the month.
        start = datetime.datetime(2026, 1, 6, 9, 0)
        occ = cal.expand_occurrences(start, {"FREQ": "MONTHLY", "BYDAY": "TU"},
                                     datetime.datetime(2026, 3, 1))
        self.assertEqual([o.day for o in occ if o.month == 1], [6, 13, 20, 27])
        self.assertTrue(all(o.strftime("%a") == "Tue" for o in occ))

    def test_monthly_byday_and_bymonthday_intersect(self):
        # The RFC 5545 "Friday the 13th" form: the day must satisfy BOTH.
        start = datetime.datetime(2026, 1, 13, 9, 0)
        occ = cal.expand_occurrences(
            start, {"FREQ": "MONTHLY", "BYDAY": "FR", "BYMONTHDAY": "13"},
            datetime.datetime(2026, 7, 1))
        self.assertEqual([(o.month, o.day, o.strftime("%a")) for o in occ],
                         [(2, 13, "Fri"), (3, 13, "Fri")])

    def test_monthly_byday_absent_ordinal_skips_the_month(self):
        # 5MO only exists in months with five Mondays; a four-Monday month yields nothing.
        start = datetime.datetime(2026, 2, 2, 9, 0)   # Feb 2026: 4 Mondays
        occ = cal.expand_occurrences(start, {"FREQ": "MONTHLY", "BYDAY": "5MO"},
                                     datetime.datetime(2026, 4, 1))
        self.assertEqual([(o.month, o.day) for o in occ], [(3, 30)])

    def test_yearly_leap(self):
        start = datetime.datetime(2024, 2, 29, 9, 0)
        occ = cal.expand_occurrences(start, {"FREQ": "YEARLY", "COUNT": "2"},
                                     datetime.datetime(2032, 1, 1))
        self.assertEqual([o.year for o in occ], [2024, 2028])

    def test_until_filter(self):
        start = datetime.datetime(2026, 1, 1, 9, 0)
        occ = cal.expand_occurrences(
            start, {"FREQ": "DAILY", "UNTIL": "20260103"}, datetime.datetime(2026, 3, 1))
        self.assertEqual([o.day for o in occ], [1, 2, 3])

    def test_unsupported_freq_returns_empty(self):
        start = datetime.datetime(2026, 1, 1)
        self.assertEqual(cal.expand_occurrences(start, {"FREQ": "HOURLY"},
                                                datetime.datetime(2026, 3, 1)), [])

    def test_no_rule_returns_start(self):
        start = datetime.datetime(2026, 1, 1)
        self.assertEqual(cal.expand_occurrences(start, None, start), [start])


class RecurrenceRowTests(unittest.TestCase):
    def test_rule_and_exdate_combine(self):
        rows = [("e1", "RRULE:FREQ=DAILY;COUNT=5"),
                ("e1", "EXDATE:20260103T090000")]
        combined = cal.parse_recurrence_rows(rows)
        self.assertEqual(combined["e1"]["rule"]["FREQ"], "DAILY")
        self.assertEqual(len(combined["e1"]["exdate"]), 1)

    def test_rdate_collected(self):
        combined = cal.parse_recurrence_rows([("e1", "RDATE:20260201T090000")])
        self.assertEqual(len(combined["e1"]["rdate"]), 1)


class RegistryTests(unittest.TestCase):
    def test_registry_parses_name_type_uri_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            prefs = pathlib.Path(d) / "prefs.js"
            prefs.write_text(
                'user_pref("calendar.registry.abc.name", "Personal");\n'
                'user_pref("calendar.registry.abc.type", "caldav");\n'
                'user_pref("calendar.registry.abc.uri", "https://nc.example/dav/");\n'
                'user_pref("calendar.registry.abc.disabled", false);\n')
            reg = cal.registry(prefs)
            self.assertEqual(reg["abc"]["name"], "Personal")
            self.assertEqual(reg["abc"]["type"], "caldav")
            self.assertEqual(reg["abc"]["uri"], "https://nc.example/dav/")
            self.assertFalse(reg["abc"]["disabled"])

    def test_registry_missing_file(self):
        self.assertEqual(cal.registry(pathlib.Path("/nonexistent/prefs.js")), {})

    def test_registry_disabled_true(self):
        with tempfile.TemporaryDirectory() as d:
            prefs = pathlib.Path(d) / "prefs.js"
            prefs.write_text('user_pref("calendar.registry.x.disabled", true);\n')
            self.assertTrue(cal.registry(prefs)["x"]["disabled"])


class ProfileTests(unittest.TestCase):
    def _ini(self, text):
        d = tempfile.mkdtemp()
        base = pathlib.Path(d) / "thunderbird"
        base.mkdir()
        (base / "profiles.ini").write_text(text)
        return base

    def test_prefers_default_release(self):
        base = self._ini("[Profile0]\nPath=a.default\nIsRelative=1\n"
                         "[Profile1]\nPath=b.default-release\nIsRelative=1\n")
        (base / "b.default-release").mkdir()
        (base / "a.default").mkdir()
        self.assertEqual(cal._profile_from_ini(base / "profiles.ini", base).name,
                         "b.default-release")

    def test_install_section_default_wins(self):
        base = self._ini("[Profile0]\nPath=wrong.default-release\nIsRelative=1\n"
                         "[InstallABC]\nDefault=real.default-release\n")
        (base / "real.default-release").mkdir()
        (base / "wrong.default-release").mkdir()
        self.assertEqual(cal._profile_from_ini(base / "profiles.ini", base).name,
                         "real.default-release")

    def test_default_flag_fallback(self):
        base = self._ini("[Profile0]\nPath=x.default\nIsRelative=1\n")
        (base / "x.default").mkdir()
        self.assertEqual(cal._profile_from_ini(base / "profiles.ini", base).name, "x.default")

    def test_explicit_profile(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(cal.find_profile(d).name, pathlib.Path(d).name)

    def test_missing_ini_uses_default_dir(self):
        d = tempfile.mkdtemp()
        base = pathlib.Path(d) / "thunderbird"
        (base / "u1ntdhub.default-release").mkdir(parents=True)
        os.environ["XDG_CONFIG_HOME"] = d
        try:
            self.assertEqual(cal.find_profile().name, "u1ntdhub.default-release")
        finally:
            del os.environ["XDG_CONFIG_HOME"]


class ConfigTests(unittest.TestCase):
    def test_load_config_user_overrides_shipped(self):
        with tempfile.TemporaryDirectory() as d:
            user = pathlib.Path(d) / "calendar.json"
            user.write_text(json.dumps({"default_calendar": "Personal"}))
            cfg = cal.load_config(user)
            self.assertEqual(cfg["default_calendar"], "Personal")
            self.assertIn("aggregate", cfg)      # shipped key survives

    def test_save_config_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            # two missing levels: parents=True is required to create them
            path = pathlib.Path(d) / "a" / "b" / "calendar.json"
            cal.save_config({"default_calendar": "X"}, path)
            self.assertEqual(json.loads(path.read_text())["default_calendar"], "X")
            # saving again into the existing directory must not raise (exist_ok)
            cal.save_config({"default_calendar": "Y"}, path)
            self.assertEqual(json.loads(path.read_text())["default_calendar"], "Y")

    def test_load_config_aggregate_is_on_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = cal.load_config(pathlib.Path(d) / "absent.json")
            self.assertIs(cfg["aggregate"], True)

    def test_resolve_default_by_id_then_name(self):
        cals = [{"id": "uuid-1", "name": "Home"}, {"id": "uuid-2", "name": "Work"}]
        self.assertEqual(cal.resolve_default({"default_calendar": "uuid-2"}, cals)["name"], "Work")
        self.assertEqual(cal.resolve_default({"default_calendar": "work"}, cals)["name"], "Work")

    def test_resolve_default_unknown_falls_back_to_first(self):
        cals = [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]
        self.assertEqual(cal.resolve_default({"default_calendar": "zzz"}, cals)["id"], "a")

    def test_resolve_default_empty(self):
        self.assertIsNone(cal.resolve_default({"default_calendar": "x"}, []))


class AggregationTests(unittest.TestCase):
    def _event(self, cal_id, eid, title, day=1):
        return {"calendar": cal_id, "id": eid, "title": title,
                "start_usecs": day * USECS, "end_usecs": (day + 1) * USECS}

    def test_merge_prefers_default(self):
        events = [self._event("other", "e1", "from-other"),
                  self._event("home", "e1", "from-default")]
        merged = cal.merge_events(events, "home")
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["title"], "from-default")

    def test_merge_keeps_distinct(self):
        events = [self._event("home", "e1", "a"), self._event("home", "e2", "b")]
        self.assertEqual(len(cal.merge_events(events, "home")), 2)

    def test_combine_plan_additions_and_collisions(self):
        events = [self._event("home", "e1", "shared"),
                  self._event("work", "e1", "shared-copy"),
                  self._event("work", "e2", "only-in-work")]
        additions, collisions = cal.combine_plan(events, "home")
        self.assertEqual([e["title"] for e in additions], ["only-in-work"])
        self.assertEqual([e["title"] for e in collisions], ["shared-copy"])

    def test_promote_plan_targets_every_other_calendar(self):
        events = [self._event("home", "e1", "x"), self._event("work", "e9", "y")]
        plan = cal.promote_plan(events, "home", ["work", "personal", "home"])
        self.assertEqual(len(plan), 2)                    # one per other calendar
        self.assertEqual({p["target"] for p in plan}, {"work", "personal"})

    def test_event_key_is_the_event_id(self):
        # identity ignores the calendar, so a copied event shares a key
        self.assertEqual(cal.event_key(self._event("h", "e", "t")), "e")
        self.assertEqual(cal.event_key(self._event("other", "e", "t2")), "e")


class OccurrencesOfTests(unittest.TestCase):
    def test_absent_allday_and_floating_default_to_false(self):
        # an event dict without the flags must be read as a zoned event (local time),
        # not as all-day/UTC midnight.
        us = int(datetime.datetime(2026, 6, 5, 9, tzinfo=datetime.timezone.utc).timestamp()) * USECS
        event = {"id": "e", "calendar": "c", "start_usecs": us,
                 "end_usecs": us + 3600 * USECS, "status": ""}
        with non_utc_zone():
            start, _ = cal.occurrences_of(event, datetime.datetime(2026, 6, 6))[0]
            self.assertEqual(start, datetime.datetime.fromtimestamp(us // USECS))
            self.assertNotEqual(start, cal.to_display(us, allday=True))

    def test_rdate_at_master_start_does_not_duplicate(self):
        us = int(datetime.datetime(2026, 6, 5, 9).timestamp()) * USECS
        event = {"id": "e", "calendar": "c", "start_usecs": us, "end_usecs": us + 3600 * USECS,
                 "status": "", "allday": False, "floating": False,
                 "rule": {"FREQ": "DAILY", "COUNT": "2"},
                 "rdate": [cal.to_display(us)], "exdate": set(), "exceptions": set()}
        occ = cal.occurrences_of(event, datetime.datetime(2026, 6, 10))
        starts = [s for s, _ in occ]
        self.assertEqual(len(starts), len(set(starts)))          # no duplicate


class FormatTests(unittest.TestCase):
    def test_format_timed_event(self):
        event = {"start": "2026-06-05T09:30", "title": "Standup", "default": False}
        self.assertIn("2026-06-05 09:30", cal.format_event(event, {}, color=False))
        self.assertIn("Standup", cal.format_event(event, {}, color=False))

    def test_format_all_day_uses_date(self):
        event = {"start": "2026-06-05", "title": "Holiday", "all_day": True, "default": True}
        line = cal.format_event(event, {}, color=False)
        self.assertIn("2026-06-05", line)
        self.assertNotIn("00:00", line)

    def test_format_event_colours_by_default(self):
        event = {"start": "2026-06-05T09:30", "title": "X", "default": True}
        self.assertIn("\033[", cal.format_event(event, {"accent": "#ff0000"}))

    def test_save_config_writes_sorted_keys(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "a" / "calendar.json"
            cal.save_config({"zeta": 1, "alpha": 2}, path)
            self.assertTrue(path.read_text().startswith('{\n  "alpha": 2,'))

    def test_style_wraps_and_resets(self):
        out = cal.style("x", "#ff0000", True)
        self.assertTrue(out.startswith("\033[38;2;255;0;0m"))
        self.assertTrue(out.endswith("\033[0m"))

    def test_style_disabled_is_plain(self):
        self.assertEqual(cal.style("x", "#ff0000", False), "x")


class ThemeTests(unittest.TestCase):
    def test_load_theme_reads_hex(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "colors.toml"
            p.write_text('accent = "#82FB9C"\nbackground = "#0B0C16"\nname = "hackerman"\n')
            colors = cal.load_theme(p)
            self.assertEqual(colors["accent"], "#82FB9C")
            self.assertNotIn("name", colors)          # non-colour keys ignored

    def test_load_theme_missing(self):
        self.assertEqual(cal.load_theme("/nonexistent/colors.toml"), {})


    def test_recorded_theme_name_reads_the_hook_stamp(self):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "omarchy-calendar").mkdir()
            (pathlib.Path(d) / "omarchy-calendar" / "active-theme").write_text("tokyo-night\n")
            with unittest.mock.patch.dict(os.environ, {"XDG_STATE_HOME": d}):
                self.assertEqual(cal.recorded_theme_name(), "tokyo-night")

    def test_recorded_theme_name_empty_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            with unittest.mock.patch.dict(os.environ, {"XDG_STATE_HOME": d}):
                self.assertEqual(cal.recorded_theme_name(), "")

    def test_resolve_theme_name_matches_an_installed_theme(self):
        with tempfile.TemporaryDirectory() as d:
            theme = pathlib.Path(d) / "hackerman"
            theme.mkdir()
            (theme / "colors.toml").write_text('accent = "#82FB9C"\n')
            colors = cal.load_theme(str(theme / "colors.toml"))
            with unittest.mock.patch.object(cal, "theme_search_dirs", lambda: [theme]):
                self.assertEqual(cal.resolve_theme_name(colors), "hackerman")

    def test_omarchy_theme_name_reads_current_theme_name(self):
        with tempfile.TemporaryDirectory() as d:
            cur = pathlib.Path(d) / "omarchy" / "current"
            cur.mkdir(parents=True)
            (cur / "theme.name").write_text("Yellow On Black\n")
            with unittest.mock.patch.dict(os.environ, {"XDG_STATE_HOME": d}):
                self.assertEqual(cal.omarchy_theme_name(), "yellow-on-black")

    def test_omarchy_theme_name_empty_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            with unittest.mock.patch.dict(os.environ, {"XDG_STATE_HOME": d}):
                self.assertEqual(cal.omarchy_theme_name(), "")

    def _applied(self, *, omarchy="", match="", stamp=""):
        with unittest.mock.patch.object(cal, "omarchy_theme_name", lambda: omarchy), \
             unittest.mock.patch.object(cal, "resolve_theme_name", lambda c: match), \
             unittest.mock.patch.object(cal, "recorded_theme_name", lambda: stamp):
            return cal.applied_theme_name({})

    def test_omarchy_theme_name_beats_both_fallbacks(self):
        self.assertEqual(self._applied(omarchy="hackerman", match="gruvbox",
                                       stamp="tokyo-night"), "hackerman")

    def test_a_stale_stamp_never_wins_over_a_colour_match(self):
        self.assertEqual(self._applied(match="hackerman", stamp="tokyo-night"), "hackerman")

    def test_the_stamp_is_only_the_last_resort(self):
        self.assertEqual(self._applied(stamp="tokyo-night"), "tokyo-night")


class StoreTests(unittest.TestCase):
    def test_load_events_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            db = pathlib.Path(d) / "local.sqlite"
            start = int(datetime.datetime(2026, 6, 5, 9, 0).timestamp()) * USECS
            make_store(db, rows=[("cal1", "e1", "Standup", start, start + 3600 * USECS,
                                  None, 0, "UTC", None)])
            events = cal.load_events(db, d, "cal1")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["title"], "Standup")
            self.assertEqual(events[0]["calendar"], "cal1")

    def test_load_events_copies_from_a_separate_workdir(self):
        with tempfile.TemporaryDirectory() as profile, tempfile.TemporaryDirectory() as work:
            db = pathlib.Path(profile) / "cal.sqlite"
            start = int(datetime.datetime(2026, 6, 5, 9, 0).timestamp()) * USECS
            make_store(db, rows=[("cal1", "e1", "Copied", start, start + USECS, None, 0, "UTC", None)])
            events = cal.load_events(db, work, "cal1")
            self.assertEqual(len(events), 1)
            self.assertTrue((pathlib.Path(work) / "cal.sqlite").is_file())   # it was copied

    def test_load_events_non_store(self):
        with tempfile.TemporaryDirectory() as d:
            bad = pathlib.Path(d) / "x.sqlite"
            sqlite3.connect(str(bad)).close()
            self.assertEqual(cal.load_events(bad, d, "x"), [])

    def test_upcoming_skips_cancelled(self):
        now = datetime.datetime(2026, 6, 5, 8, 0)
        start = int(datetime.datetime(2026, 6, 5, 9, 0).timestamp()) * USECS
        events = [
            {"calendar": "c", "id": "a", "title": "live", "start_usecs": start,
             "end_usecs": start + 3600 * USECS, "status": "", "allday": False, "floating": False},
            {"calendar": "c", "id": "b", "title": "gone", "start_usecs": start,
             "end_usecs": start + 3600 * USECS, "status": "CANCELLED",
             "allday": False, "floating": False},
        ]
        shown = cal.upcoming(events, now=now, days=7)
        self.assertEqual([e["title"] for e in shown], ["live"])

    def test_upcoming_excludes_past(self):
        now = datetime.datetime(2026, 6, 5, 12, 0)
        start = int(datetime.datetime(2026, 6, 5, 9, 0).timestamp()) * USECS
        events = [{"calendar": "c", "id": "a", "title": "past", "start_usecs": start,
                   "end_usecs": start + 3600 * USECS, "status": "", "allday": False,
                   "floating": False}]
        self.assertEqual(cal.upcoming(events, now=now, days=7), [])

    def test_calendars_of_binds_local_and_registry(self):
        with tempfile.TemporaryDirectory() as d:
            profile = pathlib.Path(d)
            (profile / "calendar-data").mkdir()
            (profile / "prefs.js").write_text(
                'user_pref("calendar.registry.uuid-1.name", "Home");\n'
                'user_pref("calendar.registry.uuid-1.type", "storage");\n')
            make_store(profile / "calendar-data" / "local.sqlite")
            cals = cal.calendars_of(profile)
            names = {c["name"]: c for c in cals}
            self.assertIn("Home", names)
            self.assertIsNotNone(names["Home"]["store"])
            self.assertEqual(names["Home"]["store"].name, "local.sqlite")



class PathEnvTests(unittest.TestCase):
    def test_config_home_honours_env(self):
        with unittest.mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/tmp/xdgcfg"}):
            self.assertEqual(cal.config_home(), pathlib.Path("/tmp/xdgcfg"))

    def test_state_home_honours_env(self):
        with unittest.mock.patch.dict(os.environ, {"XDG_STATE_HOME": "/tmp/xdgstate"}):
            self.assertEqual(cal.state_home(), pathlib.Path("/tmp/xdgstate"))

    def test_config_home_falls_back_to_home(self):
        env = {k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(cal.config_home(),
                             pathlib.Path.home() / ".config")


class WeekdayMapTests(unittest.TestCase):
    def test_mapping_is_the_ical_order(self):
        self.assertEqual(cal.WEEKDAYS,
                         {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6})


class UnquoteTests(unittest.TestCase):
    def test_unquote(self):
        self.assertEqual(cal._unquote('"hi"'), "hi")
        self.assertEqual(cal._unquote('""'), "")      # a two-char quoted empty string
        self.assertEqual(cal._unquote("bare"), "bare")


class ProfileFinderMoreTests(unittest.TestCase):
    def _base(self, ini):
        d = tempfile.mkdtemp()
        base = pathlib.Path(d) / "thunderbird"
        base.mkdir()
        (base / "profiles.ini").write_text(ini)
        return base

    def test_find_profile_reads_profiles_ini(self):
        base = self._base("[Profile0]\nPath=r.default-release\nIsRelative=1\n")
        (base / "r.default-release").mkdir()
        with unittest.mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(base.parent)}):
            self.assertEqual(cal.find_profile().name, "r.default-release")

    def test_find_profile_uses_ini_result_even_without_default_in_name(self):
        # the ini's profile wins outright; it is not re-derived by scanning dirs, so
        # a profile dir whose NAME lacks "default" must still be returned.
        base = self._base("[Profile0]\nPath=profile-x\nIsRelative=1\n")
        (base / "profile-x").mkdir()
        with unittest.mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(base.parent)}):
            self.assertEqual(cal.find_profile(), base / "profile-x")

    def test_find_profile_ignores_non_default_dirs_without_ini(self):
        d = tempfile.mkdtemp()
        base = pathlib.Path(d) / "thunderbird"
        (base / "random").mkdir(parents=True)
        with unittest.mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d}):
            self.assertIsNone(cal.find_profile())

    def test_install_section_without_default_does_not_win(self):
        base = self._base("[InstallXYZ]\nLocked=1\n"
                          "[Profile0]\nPath=r.default-release\nIsRelative=1\n")
        (base / "r.default-release").mkdir()
        self.assertEqual(cal._profile_from_ini(base / "profiles.ini", base).name,
                         "r.default-release")

    def test_relative_profile_requires_BOTH_path_and_IsRelative(self):
        # rule 4 returns the first profile with Path *and* IsRelative; a section with
        # Path but no IsRelative must be skipped, not returned.
        base = self._base("[Profile0]\nPath=a.profile\n"
                          "[Profile1]\nPath=b.profile\nIsRelative=1\n")
        (base / "a.profile").mkdir()
        (base / "b.profile").mkdir()
        self.assertEqual(cal._profile_from_ini(base / "profiles.ini", base).name, "b.profile")

    def test_default_flag_beats_first_relative(self):
        base = self._base("[Profile0]\nPath=a.profile\nIsRelative=1\n"
                          "[Profile1]\nPath=b.profile\nIsRelative=1\nDefault=1\n")
        (base / "a.profile").mkdir()
        (base / "b.profile").mkdir()
        self.assertEqual(cal._profile_from_ini(base / "profiles.ini", base).name,
                         "b.profile")


class OccurrenceBoundaryTests(unittest.TestCase):
    """Boundary conditions of the occurrence generators (== horizon, == limit)."""

    def test_daily_includes_occurrence_on_horizon(self):
        start = datetime.datetime(2026, 1, 1, 9, 0)
        occ = cal._daily_occurrences(start, 1, [], datetime.datetime(2026, 1, 3, 9, 0), 100)
        self.assertEqual([o.day for o in occ], [1, 2, 3])

    def test_daily_stops_at_limit(self):
        start = datetime.datetime(2026, 1, 1, 9, 0)
        occ = cal._daily_occurrences(start, 1, [], datetime.datetime(2026, 2, 1), 3)
        self.assertEqual(len(occ), 3)

    def test_weekly_includes_occurrence_on_horizon(self):
        start = datetime.datetime(2026, 1, 5, 9, 0)          # Monday
        occ = cal._weekly_occurrences(start, 1, [], datetime.datetime(2026, 1, 19, 9, 0), 100)
        self.assertEqual([o.day for o in occ], [5, 12, 19])

    def test_weekly_stops_at_limit(self):
        start = datetime.datetime(2026, 1, 5, 9, 0)
        occ = cal._weekly_occurrences(start, 1, [], datetime.datetime(2026, 6, 1), 3)
        self.assertEqual(len(occ), 3)

    def test_weekly_byday_stops_mid_week_at_limit(self):
        start = datetime.datetime(2026, 1, 5, 9, 0)
        occ = cal._weekly_occurrences(start, 1, ["MO", "WE"], datetime.datetime(2026, 6, 1), 3)
        self.assertEqual([(o.month, o.day) for o in occ], [(1, 5), (1, 7), (1, 12)])

    def test_monthly_includes_occurrence_on_horizon(self):
        start = datetime.datetime(2026, 1, 1, 0, 0)
        occ = cal._monthly_occurrences(start, 1, [], datetime.datetime(2026, 3, 1, 0, 0), 100)
        self.assertEqual([o.month for o in occ], [1, 2, 3])

    def test_monthly_stops_at_limit(self):
        start = datetime.datetime(2026, 1, 15, 9, 0)
        occ = cal._monthly_occurrences(start, 1, [], datetime.datetime(2027, 1, 1), 3)
        self.assertEqual(len(occ), 3)

    def test_monthly_stops_mid_month_at_limit(self):
        # two days per month, so the limit is reached part-way through a month
        start = datetime.datetime(2026, 1, 1, 9, 0)
        occ = cal._monthly_occurrences(start, 1, [1, 15], datetime.datetime(2027, 1, 1), 3)
        self.assertEqual([(o.month, o.day) for o in occ], [(1, 1), (1, 15), (2, 1)])

    def test_yearly_stops_at_limit(self):
        start = datetime.datetime(2026, 3, 1, 9, 0)
        occ = cal._yearly_occurrences(start, 1, datetime.datetime(2100, 1, 1), 3)
        self.assertEqual(len(occ), 3)

    def test_datetime_until_includes_the_exact_boundary(self):
        start = datetime.datetime(2026, 1, 1, 9, 0)
        occ = cal.expand_occurrences(start, {"FREQ": "DAILY", "UNTIL": "20260103T090000"},
                                     datetime.datetime(2026, 6, 1))
        self.assertEqual([o.day for o in occ], [1, 2, 3])

    def test_monthly_horizon_before_first_returns_empty(self):
        start = datetime.datetime(2026, 6, 15, 9, 0)
        occ = cal._monthly_occurrences(start, 1, [], datetime.datetime(2026, 1, 1), 100)
        self.assertEqual(occ, [])

    def test_last_day_of_month(self):
        self.assertEqual(cal._last_day_of_month(2026, 2), 28)
        self.assertEqual(cal._last_day_of_month(2024, 2), 29)   # leap year
        self.assertEqual(cal._last_day_of_month(2026, 12), 31)
        self.assertEqual(cal._last_day_of_month(2026, 4), 30)

    def test_negative_bymonthday_counts_from_month_end(self):
        start = datetime.datetime(2026, 1, 15, 9, 0)
        occ = cal._monthly_occurrences(start, 1, [-1], datetime.datetime(2026, 4, 30, 9, 0), 100)
        self.assertEqual([(o.month, o.day) for o in occ],
                         [(1, 31), (2, 28), (3, 31), (4, 30)])
        self.assertEqual({o.hour for o in occ}, {9})            # time-of-day preserved

    def test_positive_bymonthday_first_of_month(self):
        start = datetime.datetime(2026, 1, 1, 9, 0)
        occ = cal._monthly_occurrences(start, 1, [1], datetime.datetime(2026, 4, 1, 9, 0), 100)
        self.assertEqual([(o.month, o.day) for o in occ],
                         [(1, 1), (2, 1), (3, 1), (4, 1)])

    def test_negative_bymonthday_through_expand(self):
        start = datetime.datetime(2028, 1, 10, 9, 0)
        occ = cal.expand_occurrences(start, {"FREQ": "MONTHLY", "BYMONTHDAY": "-1", "COUNT": "2"},
                                     datetime.datetime(2028, 6, 1))
        self.assertEqual([(o.month, o.day) for o in occ], [(1, 31), (2, 29)])   # 2028 is a leap year

    def test_yearly_includes_occurrence_on_horizon(self):
        start = datetime.datetime(2026, 3, 1, 9, 0)
        occ = cal._yearly_occurrences(start, 1, datetime.datetime(2028, 3, 1, 9, 0), 100)
        self.assertEqual([o.year for o in occ], [2026, 2027, 2028])



def make_full_store(path, cal_id, items):
    """A store with cal_events + cal_properties (item, title) pairs."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE cal_events (cal_id TEXT, id TEXT, time_created INTEGER, "
                 "last_modified INTEGER, title TEXT, priority INTEGER, privacy TEXT, "
                 "ical_status TEXT, flags INTEGER, event_start INTEGER, event_end INTEGER, "
                 "event_stamp INTEGER, event_start_tz TEXT, event_end_tz TEXT, "
                 "recurrence_id INTEGER, recurrence_id_tz TEXT, alarm_last_ack INTEGER, "
                 "offline_journal INTEGER)")
    conn.execute("CREATE TABLE cal_properties (item_id TEXT, key TEXT, value BLOB, "
                 "recurrence_id INTEGER, recurrence_id_tz TEXT, cal_id TEXT)")
    for eid, title in items:
        conn.execute("INSERT INTO cal_events (cal_id,id,title,event_start,event_end,flags) "
                     "VALUES (?,?,?,?,?,0)", (cal_id, eid, title, 1000 * USECS, 2000 * USECS))
        conn.execute("INSERT INTO cal_properties (item_id,key,value,cal_id) VALUES (?,?,?,?)",
                     (eid, "UID", ("uid-" + eid).encode(), cal_id))
    conn.commit()
    conn.close()


class UserConfigTests(unittest.TestCase):
    def test_load_user_config_only_user_keys(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "calendar.json"
            p.write_text(json.dumps({"default_calendar": "Work"}))
            self.assertEqual(cal.load_user_config(p), {"default_calendar": "Work"})

    def test_load_user_config_absent_is_empty(self):
        self.assertEqual(cal.load_user_config("/nonexistent/x.json"), {})


class CopyItemsTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.home = pathlib.Path(self.d) / "home.sqlite"
        self.work = pathlib.Path(self.d) / "work.sqlite"
        make_full_store(self.home, "uuid-home", [("h1", "Home event")])
        make_full_store(self.work, "uuid-work", [("w1", "Work event")])

    def _titles(self, path, cal_id):
        conn = sqlite3.connect(str(path))
        try:
            return [r[0] for r in conn.execute(
                "SELECT title FROM cal_events WHERE cal_id=? ORDER BY title", (cal_id,))]
        finally:
            conn.close()

    def test_copies_item_into_another_store_with_new_cal_id(self):
        n = cal.copy_items([(str(self.work), "uuid-work", "w1", str(self.home), "uuid-home")])
        self.assertEqual(n, 1)
        self.assertEqual(self._titles(self.home, "uuid-home"), ["Home event", "Work event"])
        self.assertEqual(self._titles(self.home, "uuid-work"), [])   # cal_id was rewritten

    def test_copies_iCal_properties_too(self):
        cal.copy_items([(str(self.work), "uuid-work", "w1", str(self.home), "uuid-home")])
        conn = sqlite3.connect(str(self.home))
        try:
            keys = [r[0] for r in conn.execute(
                "SELECT key FROM cal_properties WHERE item_id='w1' AND cal_id='uuid-home'")]
        finally:
            conn.close()
        self.assertEqual(keys, ["UID"])

    def test_without_overwrite_duplicates(self):
        move = (str(self.work), "uuid-work", "w1", str(self.home), "uuid-home")
        cal.copy_items([move])
        cal.copy_items([move])
        self.assertEqual(self._titles(self.home, "uuid-home").count("Work event"), 2)

    def test_overwrite_replaces(self):
        move = (str(self.work), "uuid-work", "w1", str(self.home), "uuid-home")
        cal.copy_items([move])
        cal.copy_items([move], overwrite=True)
        self.assertEqual(self._titles(self.home, "uuid-home").count("Work event"), 1)

    def test_same_calendar_is_skipped(self):
        n = cal.copy_items([(str(self.home), "uuid-home", "h1", str(self.home), "uuid-home")])
        self.assertEqual(n, 0)
        self.assertEqual(self._titles(self.home, "uuid-home"), ["Home event"])

    def test_missing_destination_is_skipped(self):
        n = cal.copy_items([(str(self.work), "uuid-work", "w1", "/nonexistent/x.sqlite", "c")])
        self.assertEqual(n, 0)

    def test_unknown_item_is_not_counted(self):
        n = cal.copy_items([(str(self.work), "uuid-work", "nope", str(self.home), "uuid-home")])
        self.assertEqual(n, 0)

    def test_empty_moves(self):
        self.assertEqual(cal.copy_items([]), 0)


if __name__ == "__main__":
    unittest.main()

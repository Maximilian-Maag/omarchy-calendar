"""Integration tests — the shipped CLI driven as a subprocess against a synthetic
Thunderbird profile (never the user's real one).
"""

import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = ROOT / "bin/omarchy-calendar"
USECS = 1000000


def _store(path, cal_id, events):
    """cal: events = [(id, title, start_epoch_seconds)]."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE cal_events (cal_id TEXT, id TEXT, time_created INTEGER, "
        "last_modified INTEGER, title TEXT, priority INTEGER, privacy TEXT, "
        "ical_status TEXT, flags INTEGER, event_start INTEGER, event_end INTEGER, "
        "event_stamp INTEGER, event_start_tz TEXT, event_end_tz TEXT, "
        "recurrence_id INTEGER, recurrence_id_tz TEXT, alarm_last_ack INTEGER, "
        "offline_journal INTEGER)")
    conn.execute("CREATE TABLE cal_recurrence (item_id TEXT, cal_id TEXT, icalString TEXT)")
    for eid, title, start in events:
        conn.execute("INSERT INTO cal_events (cal_id, id, title, event_start, event_end, "
                     "flags) VALUES (?,?,?,?,?,0)",
                     (cal_id, eid, title, start * USECS, (start + 3600) * USECS))
    conn.commit()
    conn.close()


class CliIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile = pathlib.Path(self.tmp.name) / "profile"
        (self.profile / "calendar-data").mkdir(parents=True)
        # two calendars: Home (default, local.sqlite) and Work (uuid-work.sqlite)
        (self.profile / "prefs.js").write_text(
            'user_pref("calendar.registry.uuid-home.name", "Home");\n'
            'user_pref("calendar.registry.uuid-home.type", "storage");\n'
            'user_pref("calendar.registry.uuid-work.name", "Work");\n'
            'user_pref("calendar.registry.uuid-work.type", "caldav");\n')
        far = 4102444800        # 2100-01-01, always "upcoming"
        _store(self.profile / "calendar-data" / "local.sqlite", "uuid-home",
               [("home-1", "Home event", far)])
        _store(self.profile / "calendar-data" / "uuid-work.sqlite", "uuid-work",
               [("work-1", "Work event", far + 3600)])
        self.config = pathlib.Path(self.tmp.name) / "calendar.json"

    def add_disabled_calendar(self):
        far = 4102444800
        _store(self.profile / "calendar-data" / "uuid-arch.sqlite", "uuid-arch",
               [("arch-1", "Archived event", far + 7200)])
        with (self.profile / "prefs.js").open("a") as fh:
            fh.write('user_pref("calendar.registry.uuid-arch.name", "Archive");\n'
                     'user_pref("calendar.registry.uuid-arch.type", "storage");\n'
                     'user_pref("calendar.registry.uuid-arch.disabled", true);\n')

    def test_disabled_non_default_calendar_is_excluded(self):
        self.add_disabled_calendar()
        data = json.loads(self.run_cli("list", "--json", "--days", "100000").stdout)
        self.assertEqual({e["calendar"] for e in data["events"]}, {"uuid-home", "uuid-work"})

    def test_disabled_calendar_shown_with_include_disabled(self):
        self.add_disabled_calendar()
        data = json.loads(self.run_cli("list", "--json", "--include-disabled",
                                       "--days", "100000").stdout)
        self.assertEqual(data["count"], 3)

    def run_cli(self, *args):
        cmd = [sys.executable, str(CLI), "--profile", str(self.profile),
               "--config", str(self.config), *args]
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_sources_json_lists_both_calendars(self):
        r = self.run_cli("sources", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        cals = json.loads(r.stdout)
        names = {c["name"]: c for c in cals}
        self.assertEqual(set(names), {"Home", "Work"})
        self.assertTrue(names["Home"]["default"])

    def test_list_json_aggregates_both(self):
        r = self.run_cli("list", "--json", "--days", "100000")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["default"], "uuid-home")

    def test_default_get_and_set(self):
        self.assertEqual(self.run_cli("default").stdout.strip(), "Home")
        r = self.run_cli("default", "Work")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Work", r.stdout)
        self.assertEqual(self.run_cli("default").stdout.strip(), "Work")
        self.assertEqual(json.loads(self.config.read_text())["default_calendar"], "uuid-work")

    def test_default_unknown_name_errors(self):
        r = self.run_cli("default", "Nonexistent")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no such calendar", r.stderr)

    def test_combine_dry_run_reports_additions(self):
        r = self.run_cli("combine", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual([a["title"] for a in data["additions"]], ["Work event"])
        self.assertIn("dry-run", self.run_cli("combine").stdout)

    def test_promote_dry_run_targets_other_calendar(self):
        r = self.run_cli("promote", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["writes"], [{"target": "uuid-work", "title": "Home event"}])

    def test_aggregate_defaults_on_and_config_can_disable_it(self):
        # same event id in both calendars: aggregation collapses them to one row
        far = 4102444800
        work_db = self.profile / "calendar-data" / "uuid-work.sqlite"
        work_db.unlink()                    # replace the setUp store with our own
        _store(work_db, "uuid-work",
               [("home-1", "Shared", far), ("work-1", "Work event", far + 3600)])
        data = json.loads(self.run_cli("list", "--json", "--days", "100000").stdout)
        self.assertEqual(data["count"], 2)                       # home-1 dedupes to one
        self.config.write_text('{"aggregate": false}')
        data = json.loads(self.run_cli("list", "--json", "--days", "100000").stdout)
        self.assertEqual(data["count"], 3)                       # both home-1 copies shown

    def test_no_aggregate_flag_overrides_config(self):
        self.config.write_text('{"aggregate": true}')
        r = self.run_cli("list", "--json", "--no-aggregate", "--days", "100000")
        self.assertEqual(json.loads(r.stdout)["count"], 2)

    def test_sources_prints_zero_for_an_empty_calendar(self):
        with (self.profile / "prefs.js").open("a") as fh:
            fh.write('user_pref("calendar.registry.uuid-empty.name", "Leer");\n'
                     'user_pref("calendar.registry.uuid-empty.type", "caldav");\n')
        out = self.run_cli("sources").stdout
        self.assertIn("0 events", out)
        self.assertNotIn("- events", out)

    def test_count_flag(self):
        self.assertEqual(self.run_cli("list", "--count", "--days", "100000").stdout.strip(), "2")

    def test_no_profile_errors(self):
        r = subprocess.run([sys.executable, str(CLI), "--profile", "/nonexistent/x",
                            "--config", str(self.config), "sources"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)

    def test_theme_from_fixture(self):
        colors = pathlib.Path(self.tmp.name) / "colors.toml"
        colors.write_text('accent = "#abcdef"\n')
        r = self.run_cli("theme", "--json", "--colors", str(colors))
        self.assertEqual(json.loads(r.stdout)["accent"], "#abcdef")


    def test_combine_apply_then_promote_apply(self):
        # combine moves Work's event into Home, then promote pushes Home's events out.
        r = self.run_cli("--force", "combine", "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("combined 1 event", r.stdout)
        r = self.run_cli("--force", "promote", "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("promoted", r.stdout)


if __name__ == "__main__":
    unittest.main()

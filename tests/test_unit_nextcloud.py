"""Unit tests for the Nextcloud CalDAV read source — all network-free.

`dav_request` is injected, so nothing here touches the network.
"""

import base64
import datetime
import importlib.machinery
import importlib.util
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = ROOT / "bin/omarchy-calendar"
_loader = importlib.machinery.SourceFileLoader("omarchy_calendar_nc", str(CLI))
_spec = importlib.util.spec_from_loader("omarchy_calendar_nc", _loader)
cal = importlib.util.module_from_spec(_spec)
_loader.exec_module(cal)

NC = {
    "base_url": "https://nc.example",
    "user": "mmaag",
    "principal": "uuid-1",
    "password": "secret",
}

MULTISTATUS = """<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
  <d:response><d:href>/remote.php/dav/calendars/uuid-1/</d:href>
    <d:propstat><d:prop><d:displayname>Home</d:displayname>
      <d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>
  <d:response><d:href>/remote.php/dav/calendars/uuid-1/personal/</d:href>
    <d:propstat><d:prop><d:displayname>Persönlich</d:displayname>
      <d:resourcetype><d:collection/><cal:calendar/></d:resourcetype></d:prop></d:propstat></d:response>
  <d:response><d:href>/remote.php/dav/calendars/uuid-1/work/</d:href>
    <d:propstat><d:prop><d:displayname></d:displayname>
      <d:resourcetype><d:collection/><cal:calendar/></d:resourcetype></d:prop></d:propstat></d:response>
</d:multistatus>"""


def vevent(dtstart="20260605T090000Z", **kw):
    props = ["BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT",
             "UID:%s" % kw.get("uid", "u1"),
             "SUMMARY:%s" % kw.get("summary", "Meeting"),
             "DTSTART:%s" % dtstart]
    if kw.get("dtend"):
        props.append("DTEND:%s" % kw["dtend"])
    if kw.get("duration"):
        props.append("DURATION:%s" % kw["duration"])
    if kw.get("rrule"):
        props.append("RRULE:%s" % kw["rrule"])
    if kw.get("exdate"):
        props.append("EXDATE:%s" % kw["exdate"])
    if kw.get("recurrence_id"):
        props.append("RECURRENCE-ID:%s" % kw["recurrence_id"])
    if kw.get("status"):
        props.append("STATUS:%s" % kw["status"])
    props += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(props) + "\r\n"


def report(*ics_blocks):
    body = "".join(
        '<d:response><d:href>/x.ics</d:href><d:propstat><d:prop>'
        '<cal:calendar-data>%s</cal:calendar-data>'
        '</d:prop></d:propstat></d:response>' % b for b in ics_blocks)
    return ('<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" '
            'xmlns:cal="urn:ietf:params:xml:ns:caldav">%s</d:multistatus>' % body)


def fake_request(mapping):
    """request(method, url, user, pw, body, depth) -> mapping[(method, url)]."""
    calls = []

    def _req(method, url, user, password, body=None, depth=None, timeout=20,
             content_type=None):
        calls.append((method, url, user, password, body))
        return mapping.get((method, url), (0, ""))

    return _req, calls


class SecretTests(unittest.TestCase):
    def test_literal_password(self):
        self.assertEqual(cal.nc_secret({"password": "p"}), "p")

    def test_command_output(self):
        self.assertEqual(cal.nc_secret({"password_command": "printf abc"}), "abc")

    def test_base64_decode(self):
        enc = base64.b64encode(b"tok").decode()
        self.assertEqual(cal.nc_secret({"password_command": "printf %s " + enc,
                                        "encoding": "base64"}), "tok")

    def test_failing_command_is_empty(self):
        self.assertEqual(cal.nc_secret({"password_command": "exit 3"}), "")

    def test_no_source_is_empty(self):
        self.assertEqual(cal.nc_secret({}), "")

    def test_bad_base64_is_empty(self):
        self.assertEqual(cal.nc_secret({"password_command": "printf '!!!'",
                                        "encoding": "base64"}), "")


class DavResponsesTests(unittest.TestCase):
    def test_parses_hrefs_and_flags_calendars(self):
        rows = cal.dav_responses(MULTISTATUS)
        self.assertEqual(len(rows), 3)
        kinds = {h.rsplit("/", 2)[-2]: p["_is_calendar"] for h, p in rows}
        self.assertFalse(kinds["uuid-1"])
        self.assertTrue(kinds["personal"])

    def test_unparsable_is_empty(self):
        self.assertEqual(cal.dav_responses("<not xml"), [])


class NextcloudCalendarsTests(unittest.TestCase):
    def test_lists_only_calendars(self):
        req, _ = fake_request({("PROPFIND", "https://nc.example/remote.php/dav/calendars/uuid-1/"):
                               (207, MULTISTATUS)})
        cals = cal.nextcloud_calendars({"nextcloud": NC}, request=req, password="secret")
        self.assertEqual([c["name"] for c in cals], ["Persönlich", "work"])
        self.assertTrue(all(c["source"] == "nextcloud" for c in cals))
        self.assertEqual(cals[0]["id"], "nc:personal")

    def test_unconfigured_is_empty(self):
        self.assertEqual(cal.nextcloud_calendars({}), [])

    def test_auth_failure_is_empty(self):
        req, _ = fake_request({("PROPFIND", "https://nc.example/remote.php/dav/calendars/uuid-1/"):
                               (401, "")})
        self.assertEqual(cal.nextcloud_calendars({"nextcloud": NC}, request=req, password="s"), [])

    def test_no_password_is_empty(self):
        self.assertEqual(cal.nextcloud_calendars({"nextcloud": NC}, password=""), [])


class IcsParseTests(unittest.TestCase):
    def test_unfold(self):
        self.assertEqual(cal.unfold_ics("A:1\r\n 2"), "A:12")

    def test_parse_extracts_properties_with_params(self):
        ev = cal.parse_ics_events(
            "BEGIN:VEVENT\r\nDTSTART;TZID=Europe/Vienna:20260605T090000\r\nSUMMARY:Hi\r\nEND:VEVENT")
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["SUMMARY"][0][0], "Hi")
        self.assertEqual(ev[0]["DTSTART"][0][1], ["TZID=Europe/Vienna"])

    def test_param_lookup(self):
        self.assertEqual(cal._param(["TZID=X", "VALUE=DATE"], "TZID"), "X")
        self.assertIsNone(cal._param([], "TZID"))

    def test_dataset_all_day(self):
        dt, allday, floating = cal.ics_datetime("20260605")
        self.assertEqual((dt.year, dt.month, dt.day, dt.hour, allday, floating),
                         (2026, 6, 5, 0, True, True))

    def test_datetime_utc_converts_to_local(self):
        dt, allday, floating = cal.ics_datetime("20260605T090000Z")
        self.assertFalse(allday)
        expected = datetime.datetime.fromtimestamp(
            datetime.datetime(2026, 6, 5, 9, tzinfo=datetime.timezone.utc).timestamp())
        self.assertEqual(dt, expected)

    def test_datetime_floating_is_wall_clock(self):
        dt, allday, floating = cal.ics_datetime("20260605T090000")
        self.assertEqual((dt.hour, dt.minute, allday, floating), (9, 0, False, True))

    def test_invalid_is_none(self):
        self.assertIsNone(cal.ics_datetime("nonsense"))

    def test_usecs_allday_is_utc_midnight(self):
        dt = datetime.datetime(2026, 6, 5)
        self.assertEqual(cal._ics_usecs(dt, True),
                         int(datetime.datetime(2026, 6, 5, tzinfo=datetime.timezone.utc)
                             .timestamp()) * cal.USECS_PER_SECOND)

    def test_duration_parsing(self):
        self.assertEqual(cal._parse_duration("PT1H30M"),
                         datetime.timedelta(hours=1, minutes=30))
        self.assertEqual(cal._parse_duration("P2D"), datetime.timedelta(days=2))
        self.assertEqual(cal._parse_duration("-PT1H"), -datetime.timedelta(hours=1))
        self.assertEqual(cal._parse_duration("junk"), datetime.timedelta(0))


class EventsFromIcsTests(unittest.TestCase):
    def test_basic_event(self):
        evs = cal._events_from_ics(vevent(dtend="20260605T100000Z"), "nc:personal")
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["title"], "Meeting")
        self.assertEqual(evs[0]["id"], "u1")
        self.assertEqual(evs[0]["calendar"], "nc:personal")
        self.assertEqual(evs[0]["end_usecs"] - evs[0]["start_usecs"], 3600 * cal.USECS_PER_SECOND)

    def test_all_day_uses_date(self):
        evs = cal._events_from_ics(vevent(dtstart="20260605"), "c")
        self.assertTrue(evs[0]["allday"])

    def test_duration_when_no_dtend(self):
        evs = cal._events_from_ics(vevent(dtstart="20260605T090000Z", duration="PT30M"), "c")
        self.assertEqual(evs[0]["end_usecs"] - evs[0]["start_usecs"], 1800 * cal.USECS_PER_SECOND)

    def test_rrule_is_parsed(self):
        evs = cal._events_from_ics(vevent(dtstart="20260605T090000Z", rrule="FREQ=WEEKLY;BYDAY=FR"),
                                   "c")
        self.assertEqual(evs[0]["rule"]["FREQ"], "WEEKLY")

    def test_exdate_collected(self):
        evs = cal._events_from_ics(vevent(dtstart="20260605T090000Z",
                                          exdate="20260612T090000Z"), "c")
        self.assertEqual(len(evs[0]["exdate"]), 1)

    def test_recurrence_id_becomes_an_exception(self):
        master = vevent(uid="u1", dtstart="20260605T090000Z", rrule="FREQ=WEEKLY")
        exc = vevent(uid="u1", dtstart="20260612T110000Z", recurrence_id="20260612T090000Z")
        evs = cal._events_from_ics(master + exc, "c")
        kinds = sorted(e.get("override_of") is not None for e in evs)
        self.assertEqual(kinds, [False, True])
        master_ev = [e for e in evs if e.get("override_of") is None][0]
        self.assertEqual(len(master_ev["exceptions"]), 1)

    def test_missing_uid_is_skipped(self):
        self.assertEqual(cal._events_from_ics(vevent(uid="") + "", "c"), [])

    def test_missing_dtstart_is_skipped(self):
        blob = "BEGIN:VEVENT\r\nUID:u1\r\nSUMMARY:x\r\nEND:VEVENT"
        self.assertEqual(cal._events_from_ics(blob, "c"), [])

    def test_raw_ics_is_kept_for_write_back(self):
        blob = vevent()
        evs = cal._events_from_ics(blob, "c")
        self.assertEqual(evs[0]["ics"], blob)

    def test_status_preserved(self):
        evs = cal._events_from_ics(vevent(status="CANCELLED"), "c")
        self.assertEqual(evs[0]["status"], "CANCELLED")


class DavPutTests(unittest.TestCase):
    NC2 = dict(NC, base_url="https://nc.example")
    CAL = {"id": "nc:personal", "uri": "/remote.php/dav/calendars/uuid-1/personal/"}
    ICS = "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:u1\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"

    def test_put_builds_the_object_url_and_is_text_calendar(self):
        req, calls = fake_request({("PUT", "https://nc.example/remote.php/dav/calendars/uuid-1/personal/u1.ics"):
                                   (201, "")})
        ok = cal.dav_put_event(self.NC2, self.CAL["uri"], "u1", self.ICS, request=req, password="s")
        self.assertTrue(ok)
        self.assertEqual(calls[0][0], "PUT")
        self.assertEqual(calls[0][4], self.ICS)          # body is the raw iCalendar

    def test_put_reports_failure(self):
        req, _ = fake_request({})
        self.assertFalse(cal.dav_put_event(self.NC2, self.CAL["uri"], "u1", self.ICS,
                                           request=req, password="s"))

    def test_put_needs_uid_and_ics(self):
        req, _ = fake_request({})
        self.assertFalse(cal.dav_put_event(self.NC2, self.CAL["uri"], "", self.ICS, request=req,
                                           password="s"))
        self.assertFalse(cal.dav_put_event(self.NC2, self.CAL["uri"], "u1", "", request=req,
                                           password="s"))

    def test_put_events_counts_only_successes(self):
        req, calls = fake_request({
            ("PUT", "https://nc.example/remote.php/dav/calendars/uuid-1/personal/u1.ics"): (201, ""),
            ("PUT", "https://nc.example/remote.php/dav/calendars/uuid-1/personal/u2.ics"): (403, ""),
        })
        n = cal.put_events({"nextcloud": self.NC2}, self.CAL,
                           [{"id": "u1", "ics": self.ICS}, {"id": "u2", "ics": self.ICS}],
                           request=req)
        self.assertEqual(n, 1)

    def test_put_events_unconfigured_is_zero(self):
        self.assertEqual(cal.put_events({}, self.CAL, [{"id": "u1", "ics": "x"}]), 0)


class NextcloudEventsTests(unittest.TestCase):
    def _cal(self):
        return {"id": "nc:personal", "uri": "/remote.php/dav/calendars/uuid-1/personal/"}

    def test_fetches_and_parses(self):
        req, calls = fake_request({("REPORT", "https://nc.example/remote.php/dav/calendars/uuid-1/personal/"):
                                   (207, report(vevent()))})
        evs = cal.nextcloud_events(self._cal(), {"nextcloud": NC}, request=req, password="secret")
        self.assertEqual(len(evs), 1)
        self.assertEqual(calls[0][0], "REPORT")
        self.assertEqual(calls[0][2], "mmaag")

    def test_prefix_agnostic_extraction(self):
        # the server may use any namespace prefix (Nextcloud/Sabre uses "cal:")
        body = report(vevent())
        body = body.replace("cal:calendar-data", "c:calendar-data")
        req, _ = fake_request({("REPORT", "https://nc.example/remote.php/dav/calendars/uuid-1/personal/"):
                               (207, body)})
        evs = cal.nextcloud_events(self._cal(), {"nextcloud": NC}, request=req, password="secret")
        self.assertEqual(len(evs), 1)

    def test_non_multistatus_is_empty(self):
        req, _ = fake_request({("REPORT", "https://nc.example/remote.php/dav/calendars/uuid-1/personal/"):
                               (404, "")})
        self.assertEqual(cal.nextcloud_events(self._cal(), {"nextcloud": NC}, request=req,
                                              password="secret"), [])

    def test_no_config_is_empty(self):
        self.assertEqual(cal.nextcloud_events(self._cal(), {}), [])


if __name__ == "__main__":
    unittest.main()

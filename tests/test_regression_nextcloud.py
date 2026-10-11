"""Regression test for the CalDAV calendar-data extraction.

BUG: the extractor matched a hard-coded `<c:calendar-data>` prefix. Nextcloud/Sabre
answers with `<cal:calendar-data>` (it chooses the prefix), so every calendar
returned **zero** events — silently, with a 207 status — while the raw REPORT body
carried hundreds of VEVENTs (measured: 212 in `Persönlich`, 67 in `Arbeit`).
"""

import importlib.machinery
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = ROOT / "bin/omarchy-calendar"
_loader = importlib.machinery.SourceFileLoader("omarchy_calendar_ncreg", str(CLI))
_spec = importlib.util.spec_from_loader("omarchy_calendar_ncreg", _loader)
cal = importlib.util.module_from_spec(_spec)
_loader.exec_module(cal)

NC = {"base_url": "https://nc.example", "user": "mmaag", "principal": "uuid-1",
      "password": "secret"}
CAL = {"id": "nc:personal", "uri": "/remote.php/dav/calendars/uuid-1/personal/"}
ICS = "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:u1\r\nSUMMARY:X\r\n" \
      "DTSTART:20260605T090000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"


def body_with(prefix):
    return ('<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" '
            'xmlns:cal="urn:ietf:params:xml:ns:caldav" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            '<d:response><d:href>/x.ics</d:href><d:propstat><d:prop>'
            '<%s:calendar-data>%s</%s:calendar-data>'
            '</d:prop></d:propstat></d:response></d:multistatus>' % (prefix, ICS, prefix))


class CalendarDataPrefixRegression(unittest.TestCase):
    def _fetch(self, prefix):
        def req(method, url, user, password, body=None, depth=None, timeout=20):
            return 207, body_with(prefix)
        return cal.nextcloud_events(CAL, {"nextcloud": NC}, request=req, password="secret")

    def test_cal_prefix_is_extracted(self):
        # the exact shape Nextcloud/Sabre returns — the one that used to yield nothing
        self.assertEqual(len(self._fetch("cal")), 1)

    def test_c_prefix_still_works(self):
        self.assertEqual(len(self._fetch("c")), 1)

    def test_other_prefixes_work(self):
        self.assertEqual(len(self._fetch("caldav")), 1)


if __name__ == "__main__":
    unittest.main()

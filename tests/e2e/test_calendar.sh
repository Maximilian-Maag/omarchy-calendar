#!/bin/bash
# e2e: build a synthetic Thunderbird profile and drive the shipped CLI against it,
# asserting the aggregated result. Uses a throwaway profile — never the real one.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLI="$ROOT/bin/omarchy-calendar"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PROFILE="$WORK/profile"
mkdir -p "$PROFILE/calendar-data"

cat > "$PROFILE/prefs.js" <<PREFS
user_pref("calendar.registry.uuid-home.name", "Home");
user_pref("calendar.registry.uuid-home.type", "storage");
user_pref("calendar.registry.uuid-work.name", "Work");
user_pref("calendar.registry.uuid-work.type", "caldav");
PREFS

python3 - "$PROFILE" <<'PY'
import sqlite3, sys, pathlib
profile = pathlib.Path(sys.argv[1])
USECS = 1000000
far = 4102444800  # 2100-01-01
def store(name, cal_id, events):
    conn = sqlite3.connect(str(profile / "calendar-data" / name))
    conn.execute("CREATE TABLE cal_events (cal_id TEXT, id TEXT, time_created INTEGER,"
                 " last_modified INTEGER, title TEXT, priority INTEGER, privacy TEXT,"
                 " ical_status TEXT, flags INTEGER, event_start INTEGER, event_end INTEGER,"
                 " event_stamp INTEGER, event_start_tz TEXT, event_end_tz TEXT,"
                 " recurrence_id INTEGER, recurrence_id_tz TEXT, alarm_last_ack INTEGER,"
                 " offline_journal INTEGER)")
    conn.execute("CREATE TABLE cal_recurrence (item_id TEXT, cal_id TEXT, icalString TEXT)")
    for eid, title, start in events:
        conn.execute("INSERT INTO cal_events (cal_id,id,title,event_start,event_end,flags)"
                     " VALUES (?,?,?,?,?,0)", (cal_id, eid, title, start*USECS, (start+3600)*USECS))
    conn.commit(); conn.close()
store("local.sqlite", "uuid-home", [("h1", "Home event", far)])
store("uuid-work.sqlite", "uuid-work", [("w1", "Work event", far+3600)])
PY

OUT="$("$CLI" --profile "$PROFILE" --config "$WORK/calendar.json" list --json --days 100000)"
echo "$OUT"
COUNT="$(python3 -c "import json,sys;print(json.load(sys.stdin)['count'])" <<<"$OUT")"
if [[ $COUNT == 2 ]]; then
  echo "e2e: ok — aggregated 2 events across 2 calendars"
  exit 0
fi
echo "e2e: FAILED (count=$COUNT)" >&2
exit 1

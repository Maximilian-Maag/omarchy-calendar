# omarchy-calendar

An [Omarchy](https://omarchy.org/) plugin that turns **Thunderbird into the single
calendar hub** of the desktop: every calendar Thunderbird knows about — the local
calendar, CalDAV calendars from your e-mail account, Nextcloud — is aggregated behind
one configurable **default** calendar.

## Why

Thunderbird already holds the calendars: it syncs the ones from your e-mail provider
and any CalDAV calendar you add (Nextcloud included). What it does *not* give you is a
single answer to "what is on my calendar" that (a) merges every calendar, (b) lets you
declare one of them authoritative, and (c) can pull scattered events into that one
place. `omarchy-calendar` adds exactly that, on top of the store Thunderbird already
maintains — no second calendar database, no daemon.

## What it does

- **Aggregated view** — `omarchy-calendar list` shows upcoming events from *every*
  calendar at once; the default calendar's copy wins when the same event is in several.
- **One default calendar** — `omarchy-calendar default <name|id>` sets which calendar
  is authoritative. The choice lives in your user config, not in the plugin.
- **`combine`** — copies events that exist only in non-default calendars *into* the
  default, so scattered information ends up in one place. Union, deduplicated by UID.
- **`promote`** — pushes the default calendar's events back out, overwriting the same
  UID in every other calendar: the default is authoritative.
- **Theme-aware** — the event list is coloured from the *applied* Omarchy theme
  (`~/.local/state/omarchy/current/theme/colors.toml`), so all 22 stock themes work
  with no per-theme code.
- **Keybinding** — `Super+Shift+Alt+C` shows the next two weeks in a floating terminal.

Both `combine` and `promote` are **dry-run by default** and refuse to write while
Thunderbird is running (it holds a lock on its stores); pass `--apply` to write and
`--force` to override the lock check.

## Requirements

- Omarchy with Thunderbird installed and at least one calendar configured.
- Python 3 (system interpreter).

## Installation

```bash
omarchy plugin add https://github.com/Maximilian-Maag/omarchy-calendar.git --enable
bash ~/.config/omarchy/plugins/Maximilian-Maag.calendar/install.sh
```

Or from a clone: `bash install.sh`.

## Usage

```bash
omarchy-calendar sources            # every calendar Thunderbird knows, and its size
omarchy-calendar list --days 14     # upcoming events, default calendar marked *
omarchy-calendar default Personal   # set the default calendar (by name or id)
omarchy-calendar combine            # dry-run: what would move into the default
omarchy-calendar combine --apply    # merge (close Thunderbird first)
omarchy-calendar promote --apply    # default overwrites the other calendars
omarchy-calendar theme --json       # the applied Omarchy palette as hex
```

## Nextcloud (CalDAV)

Add a `nextcloud` block and the account's CalDAV calendars are merged into the same
view as the Thunderbird ones (`sources` lists them, `list` shows their events, and a
Nextcloud calendar can be the default):

```json
{
  "default_calendar": "Persönlich",
  "nextcloud": {
    "base_url": "https://cloud.example",
    "user": "<login name>",
    "principal": "<DAV principal / user id>",
    "password_command": "secret-tool lookup server Nextcloud type base64 user '<keyring key>'",
    "encoding": "base64"
  }
}
```

`password_command` is run and its stdout used as the DAV password (`encoding: base64`
decodes it first) — the Nextcloud desktop client already keeps an app password in the
freedesktop keyring, so nothing secret needs to live in the config. The DAV *user* is
the login name while the `/remote.php/dav/calendars/<principal>/` path uses the user
**id**, which can differ.

`combine`/`promote` write back over CalDAV when the default (or a target) is a
Nextcloud calendar: the event's iCalendar object is `PUT` into the calendar, which is
create-or-replace keyed by UID. Dry-run is the default; pass `--apply` to write, and
`--days` to widen the window. Writes to a Thunderbird store still require Thunderbird
to be closed.

## Config

`~/.config/omarchy-calendar/calendar.json` (overrides the shipped
`config/calendar.json`):

```json
{ "default_calendar": "<name-or-id>", "aggregate": true }
```

`default_calendar` is set for you by `omarchy-calendar default <name>`.
`aggregate` (default `true`) is the default for the `list` view: when on, the same
event copied into several calendars is shown once, with the default calendar's copy
winning; `--no-aggregate` overrides it per run.

## How it reads Thunderbird

Each calendar is a SQLite store `<profile>/calendar-data/<cal-id>.sqlite`
(``CalStorageItemModel.sys.mjs``); the calendar list, names and types live in the
profile's `prefs.js` under `calendar.registry.<id>.*`. Times are **microseconds**
since the Unix epoch. Recurring events store their RRULE in `cal_recurrence.icalString`
and are expanded here (FREQ DAILY/WEEKLY/MONTHLY/YEARLY, INTERVAL, COUNT, UNTIL, BYDAY,
BYMONTHDAY); a rescheduled occurrence is a detached exception and is shown at its new
time. A running Thunderbird locks the store, so it is copied before reading.

## Testing

```bash
make test      # policy -> unit -> regression -> integration -> e2e -> shell -> mutation
make check     # policy + unit + regression
```

## Licence

MIT.

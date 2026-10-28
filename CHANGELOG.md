# Changelog

All notable changes to omarchy-calendar are documented here.

## [0.3.2] — 2026-10-28

### Fixed
- **The theme-set hook stamped `active-theme` into a file nothing read** (#2). The hook
  exists only to write `<state>/omarchy-calendar/active-theme` (its own comment says "so a
  long-running or cached view can notice a theme change and refresh"), but no code — and no
  long-running view — ever consumed it. The `theme` command now names the applied theme,
  preferring the hook's recorded value and falling back to matching the applied colours
  against the installed theme dirs (as omarchy-docker/-mpv/-tmux do), so the stamp is
  finally read. New unit + integration tests for the recorded-wins, colour-match and
  JSON-`name` paths.

## [0.3.1] — 2026-10-28

### Fixed
- **Monthly recurrence ignored BYDAY, so ordinal rules landed on the wrong day** (#1).
  `FREQ=MONTHLY;BYDAY=2TU` ("second Tuesday") expanded on the series master's
  day-of-month (the 6th, say) instead of the second Tuesday — silently wrong dates with
  no error, while `README.md` documents BYDAY support. `_monthly_occurrences` now takes
  the parsed `BYDAY` and selects the right days: a plain weekday (`TU` = every Tuesday),
  an ordinal weekday (`2TU`, `-1FR` = last Friday), and — when both are present — the
  intersection with `BYMONTHDAY` (the RFC 5545 "Friday the 13th" form). A five-Monday
  rule now correctly produces nothing in a four-Monday month. Covered by five unit tests.

## [0.3.0] — 2026-10-11

### Added
- **Writing back to Nextcloud over CalDAV.** When the default (or a promote target) is a
  Nextcloud calendar, `combine`/`promote` now `PUT` the event's iCalendar object into it
  instead of only touching Thunderbird stores — so "the default overwrites the other
  calendars" holds for the CalDAV calendars too. `PUT` is create-or-replace keyed by UID,
  so an existing event is overwritten in place and a missing one is added. Dry-run stays
  the default; `--apply` writes. `--days` selects the window (default 3650).
- Each parsed CalDAV event keeps its **raw iCalendar block** (`ics`) so write-back is
  byte-faithful rather than re-serialised.

Verified end to end against a live Nextcloud: MKCALENDAR 201 → PUT 201 → GET 200
(body carried the event) → DELETE 204, on a throwaway calendar that was then removed.

## [0.2.0] — 2026-10-11

### Added
- **Nextcloud (CalDAV) calendars as a read source.** With a `nextcloud` block in the
  config, `sources` lists the account's CalDAV calendars next to the Thunderbird ones
  and `list` merges their events into the same view (the default calendar still wins on
  a UID collision). Calendar data is fetched with a `REPORT` calendar-query and parsed
  from iCalendar (DTSTART/DTEND/DURATION, all-day, TZID/UTC/floating, RRULE, EXDATE,
  RDATE, and `RECURRENCE-ID` detached exceptions).
- Credentials come from a `password_command` (stdout used, optional base64 decode) —
  which is how the Nextcloud desktop client's app password is read from the keyring
  (`secret-tool lookup server Nextcloud …`), so no secret is stored in the config.
- `dav_request` is an injectable seam: every CalDAV test runs network-free.

### Fixed
- **CalDAV `calendar-data` extraction matched a hard-coded `c:` prefix.** Nextcloud /
  Sabre answers with `<cal:calendar-data>`, so every calendar returned **zero** events
  with a 207 status while the raw body carried hundreds (measured: 212 in *Persönlich*,
  67 in *Arbeit*). The match is now prefix-agnostic.
- Tests no longer read the user's real `~/.config/omarchy-calendar/calendar.json`
  (a machine's Nextcloud config was leaking into the e2e and integration runs).

## [0.1.3] — 2026-10-11

### Fixed
- **The theme-set hook overwrote other plugins' theme-set hook.** `omarchy-hook-install`
  names a hook after the *basename* of the file it is given, and every plugin that
  ships a `hooks/theme-set` installs to the same `~/.config/omarchy/hooks/theme-set.d/theme-set`
  — so installing this plugin clobbered omarchy-thunderbird's theme hook (and vice
  versa). The hook is now named `hooks/calendar-theme-set` and installs alongside the
  others. If you installed 0.1.0–0.1.2, re-run `install.sh` (and re-install any hook
  that was overwritten).

## [0.1.2] — 2026-10-11

### Fixed
- **Negative `BYMONTHDAY` was silently dropped.** An RRULE such as
  `FREQ=MONTHLY;BYMONTHDAY=-1` (last day of the month) produced no occurrences, so the
  event fell back to its master date: `date(..., day=-1)` raised and the day was
  skipped. It now resolves against the month length, leap years included
  (`-1` in Feb 2028 is the 29th). `_last_day_of_month` is now `calendar.monthrange`,
  which also removes a branchy leap-year calculation that had two equivalent mutants.
- Added unit coverage for `BYMONTHDAY=1` and `BYMONTHDAY=-1`.

## [0.1.1] — 2026-10-11

### Fixed
- **`combine --apply` and `promote --apply` were silent no-ops.** Both printed the
  plan, returned success, and wrote nothing — the store was byte-identical
  afterwards. They now perform the write: an item is copied between Thunderbird
  stores by moving all of its rows verbatim (cal_events, cal_properties,
  cal_recurrence, cal_alarms, cal_attendees, cal_relations, cal_attachments),
  changing only `cal_id`, so the copy stays in Thunderbird's own schema. `promote`
  deletes the destination's rows for the item first (the default is authoritative).
  Both refuse to write while Thunderbird is running (it holds the store lock) unless
  `--force` is given.
- **`default <name>` baked the shipped defaults into the user's config.** It saved the
  whole merged config, so `aggregate`/`combine` were pinned in
  `~/.config/omarchy-calendar/calendar.json` and any later change to the shipped
  defaults would be silently overridden. It now persists only the key it changes.
- **`config.aggregate` was documented but never read**, and `config.combine` was a
  knob nothing consumed. `aggregate` (default `true`) now really controls the `list`
  view's deduplication (`--no-aggregate` overrides it per run); the dead `combine`
  block is gone.
- **The shell test quoted a variable on the left of `[[ ]]`**, which the policy check
  warns on.

## [0.1.0] — 2026-10-11

### Added
- **Aggregated calendar view.** `omarchy-calendar list` merges upcoming events from
  every calendar Thunderbird knows (local, CalDAV/e-mail, Nextcloud), with the default
  calendar's copy winning when the same event appears more than once.
- **Configurable default calendar.** `omarchy-calendar default <name|id>` records the
  choice in `~/.config/omarchy-calendar/calendar.json`.
- **`combine`** — dry-run by default, copies events that exist only in non-default
  calendars into the default (union, deduplicated by UID).
- **`promote`** — dry-run by default, makes the default authoritative by overwriting
  the same UID in every other calendar.
- **`sources`** — lists every calendar with its store, type, size and default flag.
- **Theme-aware output** — colours come from the applied Omarchy theme's
  `colors.toml`, read live, so all 22 stock themes are supported with no per-theme code.
- **Hyprland keybinding** — `Super+Shift+Alt+C` shows the next two weeks.
- Reads the Thunderbird calendar store directly (microsecond timestamps, expanded
  recurrence incl. detached exceptions), copying the store so a running Thunderbird's
  lock never blocks it.
- Full test harness: unit, regression, integration, e2e, shell and mutation kinds, all
  run from `make test` (or `tools/run_tests.sh`), plus policy as code.

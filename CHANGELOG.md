# Changelog

All notable changes to omarchy-calendar are documented here.

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

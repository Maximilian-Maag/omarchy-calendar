# Changelog

All notable changes to omarchy-calendar are documented here.

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

#!/bin/bash
# omarchy-calendar install script. Run once after cloning, or re-run to update:
#
#   ./install.sh                 install / update everything
#   ./install.sh --uninstall     remove what this script installed, and only that
#   OMARCHY_CALENDAR_BIN=~/.local/bin ./install.sh   where the CLI is symlinked
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
HYPR_DIR="$CONFIG_DIR/hypr"
HYPR_MAIN="$HYPR_DIR/hyprland.lua"
FRAGMENT="$HYPR_DIR/calendar-bindings.lua"
REQUIRE_LINE='require("hypr.calendar-bindings")'
MARKER='-- omarchy-calendar keybindings'
BIN_SRC="$PLUGIN_DIR/bin/omarchy-calendar"
BIN_DEST="${OMARCHY_CALENDAR_BIN:-/usr/local/bin/omarchy-calendar}"
HOOK_SRC="$PLUGIN_DIR/hooks/calendar-theme-set"
HOOK_DEST="$CONFIG_DIR/omarchy/hooks/theme-set.d/calendar-theme-set"

say() { printf '  %s\n' "$1"; }
warn() { printf 'WARNING: %s\n' "$1" >&2; }

# Ask for root only when the destination really needs it: an override under $HOME is written directly,
# and /usr/local/bin goes through sudo the same way it always has.
as_root() {
  if (( EUID == 0 )); then "$@"
  elif command -v sudo >/dev/null 2>&1; then sudo "$@"
  else return 1
  fi
}

link() {  # link <source> <destination>
  local source="$1" dest="$2" dir
  chmod +x "$source"
  dir="$(dirname "$dest")"
  [[ -d $dir ]] || as_root mkdir -p "$dir"
  if [[ -L $dest ]] && [[ "$(readlink -f "$dest")" == "$(readlink -f "$source")" ]]; then
    say "$(basename "$dest") already on PATH."
    return 0
  fi
  if [[ -w $dir ]]; then
    ln -sf "$source" "$dest" && say "installed $dest"
  elif as_root ln -sf "$source" "$dest"; then
    say "installed $dest"
  else
    warn "could not install $dest — add $source to PATH manually."
  fi
}

unlink_ours() {  # unlink_ours <dest> <source it must point at>
  local dest="$1" source="$2"
  if [[ -L $dest ]] && [[ "$(readlink -f "$dest")" == "$(readlink -f "$source")" ]]; then
    if [[ -w "$(dirname "$dest")" ]]; then
      rm -f "$dest"
    else
      as_root rm -f "$dest" || true
    fi
    say "removed $dest"
  elif [[ -e $dest ]]; then
    warn "$dest is not a link into this checkout — left alone."
  fi
}

uninstall() {
  echo "omarchy-calendar: uninstalling"
  unlink_ours "$BIN_DEST" "$BIN_SRC"

  if [[ -f $FRAGMENT ]]; then
    rm -f "$FRAGMENT"
    say "removed $FRAGMENT"
  fi

  if [[ -f $HYPR_MAIN ]] && grep -qF "$REQUIRE_LINE" "$HYPR_MAIN"; then
    # The line is removed by exact content rather than by `sed -i`, so the user's config is only ever
    # rewritten one line smaller and no editor is asked to interpret anything in it. install.sh writes
    # the require line as a block — a blank line, a `-- omarchy-calendar keybindings` marker, then the
    # line — so the whole block comes back out: leaving the marker (and its blank line) behind would
    # stack another marker on the file at every install/uninstall cycle.
    local kept; kept="$(mktemp)"
    mapfile -t lines < "$HYPR_MAIN"
    local out=() line
    for line in "${lines[@]}"; do
      if [[ $line == "$REQUIRE_LINE" ]]; then
        if (( ${#out[@]} )) && [[ ${out[-1]} == "$MARKER" ]]; then
          unset 'out[-1]'
          if (( ${#out[@]} )) && [[ -z ${out[-1]} ]]; then
            unset 'out[-1]'
          fi
        fi
        continue
      fi
      out+=("$line")
    done
    for line in ${out[@]+"${out[@]}"}; do
      printf '%s\n' "$line"
    done > "$kept"
    mv "$kept" "$HYPR_MAIN"
    say "took the require line back out of $HYPR_MAIN"
  fi

  if [[ -f $HOOK_DEST ]]; then
    rm -f "$HOOK_DEST"
    say "removed the theme-set hook ($HOOK_DEST)"
  fi

  echo ""
  echo "Done. The CLI's own data (your calendars) was not touched."
  echo "Reload Hyprland config for the keybindings:  hyprctl reload"
}

if [[ ${1:-} == --uninstall ]]; then
  uninstall
  exit 0
fi

echo "omarchy-calendar: installing from $PLUGIN_DIR"

# ── 1. Validate the plugin ────────────────────────────────────────────────────
if command -v omarchy >/dev/null 2>&1; then
  omarchy plugin validate "$PLUGIN_DIR" && say "manifest OK."
fi

# ── 2. Put the CLI on PATH (symlink, so git pull keeps it current) ────────────
link "$BIN_SRC" "$BIN_DEST"

# ── 3. Theme-set hook ─────────────────────────────────────────────────────────
if command -v omarchy >/dev/null 2>&1; then
  omarchy hook install theme-set "$HOOK_SRC"
  say "installed the theme-set hook."
fi

# ── 4. Wire OS keybindings into Hyprland ──────────────────────────────────────
if [[ -f $HYPR_MAIN ]]; then
  cp "$PLUGIN_DIR/bin/bindings.lua" "$FRAGMENT"
  if grep -qF "$REQUIRE_LINE" "$HYPR_MAIN"; then
    say "keybindings already wired (fragment updated)."
  else
    printf '\n%s\n%s\n' "$MARKER" "$REQUIRE_LINE" >> "$HYPR_MAIN"
    say "wired keybindings into $HYPR_MAIN"
  fi
else
  warn "$HYPR_MAIN not found — add: $REQUIRE_LINE"
fi

echo ""
echo "Done. Try:  omarchy-calendar sources   /   omarchy-calendar list --days 14"

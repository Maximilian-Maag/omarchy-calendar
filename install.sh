#!/bin/bash
# omarchy-calendar install script. Run once after cloning, or re-run to update.
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "omarchy-calendar: installing from $PLUGIN_DIR"

# ── 1. Validate the plugin ────────────────────────────────────────────────────
if command -v omarchy >/dev/null 2>&1; then
  omarchy plugin validate "$PLUGIN_DIR" && echo "  manifest OK."
fi

# ── 2. Put the CLI on PATH (symlink, so git pull keeps it current) ────────────
BIN_SRC="$PLUGIN_DIR/bin/omarchy-calendar"
BIN_DEST="/usr/local/bin/omarchy-calendar"
chmod +x "$BIN_SRC"
if [[ -L "$BIN_DEST" ]] && [[ "$(readlink -f "$BIN_DEST")" == "$(readlink -f "$BIN_SRC")" ]]; then
  echo "  omarchy-calendar already on PATH."
elif (( EUID == 0 )); then
  ln -sf "$BIN_SRC" "$BIN_DEST" && echo "  Installed $BIN_DEST."
elif command -v sudo >/dev/null 2>&1; then
  sudo ln -sf "$BIN_SRC" "$BIN_DEST" && echo "  Installed $BIN_DEST."
else
  echo "  WARNING: no sudo — add $BIN_SRC to PATH manually."
fi

# ── 3. Theme-set hook ─────────────────────────────────────────────────────────
chmod +x "$PLUGIN_DIR/hooks/theme-set"
if command -v omarchy >/dev/null 2>&1; then
  omarchy hook install theme-set "$PLUGIN_DIR/hooks/theme-set"
  echo "  Installed theme-set hook."
fi

# ── 4. Wire OS keybindings into Hyprland ──────────────────────────────────────
HYPR_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"
HYPR_MAIN="$HYPR_CONFIG_DIR/hyprland.lua"
if [[ -f "$HYPR_MAIN" ]]; then
  cp "$PLUGIN_DIR/bin/bindings.lua" "$HYPR_CONFIG_DIR/calendar-bindings.lua"
  if ! grep -q "calendar-bindings" "$HYPR_MAIN"; then
    printf '\n-- omarchy-calendar keybindings\nrequire("hypr.calendar-bindings")\n' >> "$HYPR_MAIN"
    echo "  Wired keybindings into $HYPR_MAIN"
  else
    echo "  Keybindings already wired (updated)."
  fi
else
  echo "  WARNING: $HYPR_MAIN not found — add: require(\"hypr.calendar-bindings\")"
fi

echo ""
echo "Done. Try:  omarchy-calendar sources   /   omarchy-calendar list --days 14"

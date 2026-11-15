#!/bin/bash
# Shell test for install.sh — proves it reaches the hook install and the Hyprland
# keybinding wiring. It runs hermetically: a throwaway HOME/XDG dir plus stub
# `omarchy` and `sudo` on PATH, so nothing outside the temp dir is touched.
#
# It FAILS on the historical bug where install.sh chmod'd hooks/theme-set (a file
# that does not exist) instead of hooks/calendar-theme-set: under `set -euo
# pipefail` that chmod aborts the script before the hook install and the keybinding
# wiring, so neither artefact appears.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
pass=0; fail=0
ok()  { echo "  ok: $*"; pass=$((pass+1)); }
bad() { echo "  FAIL: $*"; fail=$((fail+1)); }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# ── stubs: a recording `omarchy` and a no-op `sudo` (never touch /usr/local) ──
STUBS="$WORK/stubs"
mkdir -p "$STUBS"
cat > "$STUBS/omarchy" <<'STUB'
#!/bin/bash
printf 'omarchy %s\n' "$*" >> "$OMARCHY_LOG"
case "$1 $2" in
  "plugin validate"|"hook install") exit 0 ;;
esac
exit 0
STUB
cat > "$STUBS/sudo" <<'STUB'
#!/bin/bash
exit 0
STUB
chmod +x "$STUBS/omarchy" "$STUBS/sudo"

# ── a hermetic HOME with a Hyprland config so the keybinding path triggers ────
export HOME="$WORK/home"
export XDG_CONFIG_HOME="$HOME/.config"
export OMARCHY_LOG="$WORK/omarchy.log"
mkdir -p "$XDG_CONFIG_HOME/hypr"
: > "$XDG_CONFIG_HOME/hypr/hyprland.lua"
: > "$OMARCHY_LOG"

export PATH="$STUBS:/usr/bin:/bin:/usr/local/bin"

bash "$ROOT/install.sh" >"$WORK/out.log" 2>&1
rc=$?

# 1. the installer must run to completion (the broken chmod aborts it)
if [[ $rc == 0 ]]; then
  ok "install.sh exits 0"
else
  bad "install.sh aborted (rc=$rc): $(tail -n1 "$WORK/out.log")"
fi

# 2. the theme-set hook is handed to omarchy (only reached after the chmod)
if grep -q "hook install theme-set $ROOT/hooks/calendar-theme-set" "$OMARCHY_LOG"; then
  ok "theme-set hook installed"
else
  bad "theme-set hook was not installed (log: $(tr '\n' ';' < "$OMARCHY_LOG"))"
fi

# 3. the Hyprland keybindings are wired in
BINDINGS="$XDG_CONFIG_HOME/hypr/calendar-bindings.lua"
MAIN="$XDG_CONFIG_HOME/hypr/hyprland.lua"
if [[ -f "$BINDINGS" && -f "$MAIN" ]] && grep -q "calendar-bindings" "$MAIN"; then
  ok "keybindings wired into hyprland.lua"
else
  bad "keybindings were not wired (main exists: $([[ -f "$MAIN" ]] && echo yes || echo no))"
fi

# 4. the copied keybindings are the shipped ones, and everything landed under the
#    temp HOME (nothing outside it was written)
if cmp -s "$ROOT/bin/bindings.lua" "$BINDINGS" && [[ $HOME == "$WORK"/* ]]; then
  ok "shipped bindings copied; ran under a temp HOME"
else
  bad "bindings content or HOME isolation wrong (HOME=$HOME)"
fi

echo
if (( fail == 0 )); then echo "shell: all $pass passed"; exit 0; else echo "shell: $fail failed"; exit 1; fi

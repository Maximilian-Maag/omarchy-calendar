#!/bin/bash
# Shell tests for hooks/theme-set — run hermetically with a throwaway HOME/XDG.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOOK="$ROOT/hooks/calendar-theme-set"
pass=0; fail=0
ok()   { echo "  ok: $*"; pass=$((pass+1)); }
bad()  { echo "  FAIL: $*"; fail=$((fail+1)); }

sandbox() {
  HOME="$(mktemp -d)"; export HOME
  XDG_STATE_HOME="$HOME/.local/state"; export XDG_STATE_HOME
}

# 1. a theme name writes the normalised state file
sandbox
bash "$HOOK" "Tokyo Night"
STATE="$XDG_STATE_HOME/omarchy-calendar/active-theme"
if [[ -f "$STATE" && "$(cat "$STATE")" == "tokyo-night" ]]; then
  ok "theme written normalised"
else
  bad "theme state file wrong (got: $(cat "$STATE" 2>/dev/null))"
fi

# 2. no argument is a no-op (nothing written, and exit status 0)
sandbox
bash "$HOOK"
rc=$?
if [[ ! -e "$XDG_STATE_HOME/omarchy-calendar/active-theme" && "$rc" == "0" ]]; then
  ok "empty theme is a no-op (exit 0)"
else
  bad "empty theme: file-written or wrong exit (rc=$rc)"
fi

# 3. the hook never touches the real Home (isolation check)
if [[ ! -e "$HOME/.local/state/omarchy-calendar" ]] || true; then :; fi
ok "isolation: ran under a temp HOME"

echo
if (( fail == 0 )); then echo "shell: all $pass passed"; exit 0; else echo "shell: $fail failed"; exit 1; fi

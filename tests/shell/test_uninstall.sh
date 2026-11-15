#!/bin/bash
# install.sh --uninstall contract: it takes back exactly what install added, and nothing else.
#
# The part a user only notices later is the round trip: install appends a require block (a blank line,
# a marker comment, then the line) to a file that is *theirs*, so the uninstall has to put that file
# back byte for byte — leaving the marker behind stacks another one on every install/uninstall cycle.
# It runs hermetically: a throwaway HOME/XDG_CONFIG_HOME, a temp bin directory, and stubbed `omarchy`
# and `sudo`, so nothing outside the temp directory (and never the real /usr/local/bin) is touched.
set -uo pipefail
unset XDG_CONFIG_HOME XDG_STATE_HOME

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
INSTALL="$REPO/install.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0
check() {  # check <name> <expected> <actual>
  if [[ $2 == "$3" ]]; then
    pass=$((pass + 1)); printf '  ok    %s\n' "$1"
  else
    fail=$((fail + 1)); printf '  FAIL  %s\n        expected: %s\n        actual:   %s\n' "$1" "$2" "$3"
  fi
}
check_contains() {  # check_contains <name> <needle> <haystack>
  if [[ $3 == *"$2"* ]]; then
    pass=$((pass + 1)); printf '  ok    %s\n' "$1"
  else
    fail=$((fail + 1)); printf '  FAIL  %s\n        wanted: %s\n        in:     %s\n' "$1" "$2" "$3"
  fi
}

MARKER='-- omarchy-calendar keybindings'
REQUIRE='require("hypr.calendar-bindings")'

# ── the fake desktop ─────────────────────────────────────────────────────────
FAKEBIN="$TMP/fakebin"
LOG="$TMP/desktop.log"
mkdir -p "$FAKEBIN" "$TMP/bin"
# The stub does what the real command does for the one call the install makes: it records the call and
# copies the hook to where `omarchy hook install theme-set` puts it, so the uninstall has a real file
# to find.
cat > "$FAKEBIN/omarchy" <<STUB
#!/bin/bash
printf 'omarchy %s\n' "\$*" >> "$LOG"
if [[ "\$1 \$2" == "hook install" ]]; then
  dest="\$XDG_CONFIG_HOME/omarchy/hooks/theme-set.d/\$(basename "\$4")"
  mkdir -p "\$(dirname "\$dest")"
  cp "\$4" "\$dest"
fi
exit 0
STUB
cat > "$FAKEBIN/sudo" <<STUB
#!/bin/bash
printf 'sudo %s\n' "\$*" >> "$LOG"
exit 0
STUB
chmod +x "$FAKEBIN/omarchy" "$FAKEBIN/sudo"

export HOME="$TMP/home"
export XDG_CONFIG_HOME="$TMP/config"
export PATH="$FAKEBIN:/usr/bin:/bin:/usr/local/bin"
mkdir -p "$HOME" "$XDG_CONFIG_HOME/hypr"
: > "$LOG"

CLI="$TMP/bin/omarchy-calendar"
HYPR="$XDG_CONFIG_HOME/hypr"
MAIN="$HYPR/hyprland.lua"
FRAGMENT="$HYPR/calendar-bindings.lua"
HOOK="$XDG_CONFIG_HOME/omarchy/hooks/theme-set.d/calendar-theme-set"

run() { OMARCHY_CALENDAR_BIN="$CLI" bash "$INSTALL" "$@"; }

printf 'install.sh --uninstall contract\n'

# ── a full install, then the round trip on the user's own config ─────────────
printf -- '-- my own hyprland.lua\nhl.monitor({ output = "eDP-1" })\n' > "$MAIN"
before="$(sha256sum "$MAIN" | cut -d' ' -f1)"

out="$(run 2>&1)"; code=$?
check "installing succeeds" "0" "$code"
check "the CLI is linked into the bin directory" "$REPO/bin/omarchy-calendar" "$(readlink -f "$CLI")"
check "the bindings fragment is copied" "yes" "$([[ -f $FRAGMENT ]] && echo yes || echo no)"
check "the copied fragment is the shipped one" "0" \
      "$(cmp -s "$REPO/bin/bindings.lua" "$FRAGMENT"; echo $?)"
check "the require line is added once" "1" "$(grep -cF "$REQUIRE" "$MAIN")"
check "with its marker" "1" "$(grep -cF -- "$MARKER" "$MAIN")"
check_contains "the theme-set hook goes through omarchy" "omarchy hook install theme-set $REPO/hooks/calendar-theme-set" "$(cat "$LOG")"
check "and landed where the uninstall will look" "yes" "$([[ -f $HOOK ]] && echo yes || echo no)"

out="$(run --uninstall 2>&1)"; code=$?
check "uninstalling succeeds" "0" "$code"
check "an install/uninstall round-trip leaves hyprland.lua byte-identical" "$before" \
      "$(sha256sum "$MAIN" | cut -d' ' -f1)"
check "no marker is left behind to stack up" "0" "$(grep -cF -- "$MARKER" "$MAIN")"
check "and no blank line trail is left either" "0" \
      "$(grep -c '^$' "$MAIN" | tr -d ' ')"
check_contains "the user's own config survives" "-- my own hyprland.lua" "$(cat "$MAIN")"
check "the CLI link is gone" "no" "$([[ -e $CLI ]] && echo yes || echo no)"
check "the bindings fragment is gone" "no" "$([[ -e $FRAGMENT ]] && echo yes || echo no)"
check "the installed hook is gone" "no" "$([[ -e $HOOK ]] && echo yes || echo no)"
check_contains "and the uninstall says what it removed" "removed the theme-set hook" "$out"

# ── a hand-added require line (no marker): only that line goes ───────────────
printf -- '-- my own hyprland.lua\n%s\n' "$REQUIRE" > "$MAIN"
before="$(sha256sum "$MAIN" | cut -d' ' -f1)"
run --uninstall >/dev/null 2>&1
check "a hand-added require line is removed" "0" "$(grep -cF "$REQUIRE" "$MAIN")"
check "without eating the user's own line above it" "-- my own hyprland.lua" "$(cat "$MAIN")"
check "and that config is otherwise the same one line shorter" \
      "$(printf -- '-- my own hyprland.lua\n' | sha256sum | cut -d' ' -f1)" \
      "$(sha256sum "$MAIN" | cut -d' ' -f1)"

# A marker with no blank line before it must not take the user's own line above it with it.
printf -- '-- my own hyprland.lua\n%s\n%s\n' "$MARKER" "$REQUIRE" > "$MAIN"
run --uninstall >/dev/null 2>&1
check "a marker with no blank line above it does not eat the user's own line" \
      "-- my own hyprland.lua" "$(cat "$MAIN")"

# ── a config with nothing of ours is not rewritten at all ────────────────────
printf -- '-- a config without our line\n' > "$MAIN"
before="$(sha256sum "$MAIN" | cut -d' ' -f1)"
out="$(run --uninstall 2>&1)"
check "a config without our line is left byte-identical" "$before" "$(sha256sum "$MAIN" | cut -d' ' -f1)"
check "and nothing is claimed about removing a line" "0" \
      "$(printf '%s' "$out" | grep -c 'took the require line' | tr -d ' ')"

# ── a foreign file or symlink is left alone, and the refusal is reported ──────
ln -sfn /bin/true "$CLI"
out="$(run --uninstall 2>&1)"
check "a foreign symlink is left alone" "/bin/true" "$(readlink "$CLI")"
check_contains "and the refusal is reported" "left alone" "$out"

rm -f "$CLI"
printf 'not ours\n' > "$CLI"
out="$(run --uninstall 2>&1)"
check "a foreign file is left alone" "not ours" "$(cat "$CLI")"
check_contains "and that refusal is reported too" "left alone" "$out"
rm -f "$CLI"

# ── uninstalling nothing is not an error ─────────────────────────────────────
run --uninstall >/dev/null 2>&1
check "uninstalling nothing succeeds" "0" "$?"

printf 'install.sh --uninstall contract: %d passed, %d failed\n' "$pass" "$fail"
(( fail == 0 ))

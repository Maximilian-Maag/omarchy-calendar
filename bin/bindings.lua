-- Hyprland keybindings added by omarchy-calendar.
-- Sourced from hyprland.lua by install.sh (require("hypr.calendar-bindings")).
--
-- Super+Shift+C already opens Thunderbird's Calendar space (installed by
-- omarchy-thunderbird); these keys add the *aggregated* view on top of it.

-- Show upcoming events across every calendar, in a floating terminal.
-- The app-id org.omarchy.* makes Omarchy auto-float the window.
hl.unbind("SUPER + SHIFT + ALT + C")
o.bind("SUPER + SHIFT + ALT + C", "Upcoming events",
       "xdg-terminal-exec --app-id=org.omarchy.calendar --title='Calendar' -- "
       .. "omarchy-calendar list --days 14; echo; echo 'Press Enter to close.'; read")

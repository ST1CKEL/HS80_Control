#!/bin/sh
# Starts the graphical HS80 Control installer on Fedora (KDE Plasma or GNOME).
# The window needs GTK 4, libadwaita and PyGObject; a stock KDE installation
# may lack them, so they are installed first if necessary.
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
needed="python3 python3-gobject gtk4 libadwaita"

say() {
    case "${LANG:-}" in
        de*) printf '%s\n' "$1" ;;
        *) printf '%s\n' "$2" ;;
    esac
}

has_toolkit() {
    command -v python3 >/dev/null 2>&1 && python3 - <<'PY' >/dev/null 2>&1
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
PY
}

if ! has_toolkit; then
    if ! command -v dnf >/dev/null 2>&1; then
        say "Dieser Installer ist für Fedora gebaut (dnf fehlt)." \
            "This installer is built for Fedora (dnf is missing)." >&2
        exit 1
    fi
    say "Die Installationsoberfläche braucht noch: $needed" \
        "The installer window still needs: $needed"
    if [ -t 0 ] && command -v sudo >/dev/null 2>&1; then
        # shellcheck disable=SC2086
        sudo dnf install -y $needed
    else
        # shellcheck disable=SC2086
        pkexec dnf install -y $needed
    fi
    if ! has_toolkit; then
        say "GTK 4 und libadwaita ließen sich nicht einrichten." \
            "GTK 4 and libadwaita could not be set up." >&2
        exit 1
    fi
fi

exec python3 "$here/hs80_installer.py" "$@"

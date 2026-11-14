#!/bin/sh
# HS80 Control installer for Fedora (KDE Plasma and GNOME).
# Self-extracting: everything after the __PAYLOAD__ line is a tar.gz with the
# installer, its logos and the RPM. Run with:  sh hs80-control-installer-*.run
set -eu
directory=$(mktemp -d "${TMPDIR:-/tmp}/hs80-installer.XXXXXX")
trap 'rm -rf "$directory"' EXIT HUP INT TERM
start=$(awk '/^__PAYLOAD__$/ { print NR + 1; exit }' "$0")
tail -n +"$start" "$0" | tar -xz -C "$directory"
sh "$directory/install.sh" "$@"
exit $?
__PAYLOAD__

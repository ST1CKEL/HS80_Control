PREFIX ?= /usr
DESTDIR ?=
PYTHON ?= python3
INSTALL ?= install

PACKAGE = hs80-control
VERSION = $(shell sed -n 's/^__version__[[:space:]]*=[[:space:]]*"\([^"]*\)"/\1/p' src/hs80_control/__init__.py)
RELEASE_DATE = $(shell sed -n 's/.*<release version="$(VERSION)" date="\([^"]*\)".*/\1/p' data/metainfo/io.github.hs80control.App.metainfo.xml | head -n 1)
SOURCE_DATE_EPOCH ?= $(shell date --utc --date='$(RELEASE_DATE) 00:00:00' +%s 2>/dev/null)
DIST_BASENAME = $(PACKAGE)-$(VERSION)
DIST_ARCHIVE = dist/$(DIST_BASENAME).tar.gz
DIST_INPUTS = .github LICENSE LICENSE.CC0 Makefile NOTICE README.md bin data docs packaging src tests

LIBDIR = $(DESTDIR)$(PREFIX)/lib/hs80-control
BINDIR = $(DESTDIR)$(PREFIX)/bin
LIBEXECDIR = $(DESTDIR)$(PREFIX)/libexec
DATADIR = $(DESTDIR)$(PREFIX)/share

.PHONY: all test check check-version check-prefix check-home dist FORCE install \
	install-user uninstall uninstall-user clean

all: check

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

check-version:
	@test -n "$(VERSION)" || { echo "Could not read __version__ from src/hs80_control/__init__.py" >&2; exit 1; }
	@spec_version="$$(sed -n 's/^Version:[[:space:]]*//p' packaging/hs80-control.spec | head -n 1)"; \
	metainfo_version="$$(sed -n 's/.*<release version="\([^"]*\)".*/\1/p' data/metainfo/io.github.hs80control.App.metainfo.xml | head -n 1)"; \
	test "$$spec_version" = "$(VERSION)" || { echo "Version mismatch: Python=$(VERSION), RPM=$$spec_version" >&2; exit 1; }; \
	test "$$metainfo_version" = "$(VERSION)" || { echo "Version mismatch: Python=$(VERSION), AppStream=$$metainfo_version" >&2; exit 1; }

check: check-version test
	PYTHONPATH=src $(PYTHON) -m compileall -q src tests
	sh -n bin/hs80-control bin/hs80ctl bin/hs80d
	desktop-file-validate data/applications/io.github.hs80control.App.desktop
	appstreamcli validate --no-net --strict data/metainfo/io.github.hs80control.App.metainfo.xml
	xmllint --noout data/metainfo/io.github.hs80control.App.metainfo.xml data/icons/io.github.hs80control.App.svg
	udevadm verify --no-summary data/udev/70-hs80-control.rules
	systemd-analyze --user --man=no verify data/systemd/hs80d.service data/systemd/hs80-spatial.service
	systemd-analyze --user --man=no verify data/systemd/hs80d-user-local.service

check-prefix:
	@test "$(PREFIX)" = /usr || { \
		echo "Unsupported PREFIX=$(PREFIX): launchers and service activation use /usr; use PREFIX=/usr with DESTDIR for staged installs." >&2; \
		exit 1; \
	}

check-home:
	@test -n "$(HOME)" && test "$(HOME)" != / || { echo "Refusing user install/uninstall with unsafe HOME=$(HOME)" >&2; exit 1; }

dist: check-version $(DIST_ARCHIVE)

$(DIST_ARCHIVE): FORCE $(DIST_INPUTS)
	@test -n "$(SOURCE_DATE_EPOCH)" || { echo "Could not derive SOURCE_DATE_EPOCH from AppStream release date $(RELEASE_DATE)" >&2; exit 1; }
	mkdir -p "$(@D)"
	tar --sort=name --format=gnu --owner=0 --group=0 --numeric-owner \
		--mtime="@$(SOURCE_DATE_EPOCH)" --mode='u+rwX,go+rX,go-w' \
		--exclude-vcs --exclude='__pycache__' --exclude='*.py[cod]' \
		--transform='s,^,$(DIST_BASENAME)/,' \
		--use-compress-program='gzip -n' -cf "$@.tmp" $(DIST_INPUTS)
	mv -f "$@.tmp" "$@"

FORCE:

install: check-prefix
	$(INSTALL) -d "$(LIBDIR)/hs80_control" "$(BINDIR)" "$(LIBEXECDIR)"
	$(INSTALL) -m 0644 src/hs80_control/*.py "$(LIBDIR)/hs80_control/"
	$(INSTALL) -m 0755 bin/hs80-control bin/hs80ctl "$(BINDIR)/"
	$(INSTALL) -m 0755 bin/hs80d "$(LIBEXECDIR)/hs80d"
	$(INSTALL) -D -m 0644 data/udev/70-hs80-control.rules "$(DESTDIR)$(PREFIX)/lib/udev/rules.d/70-hs80-control.rules"
	$(INSTALL) -D -m 0644 data/systemd/hs80d.service "$(DESTDIR)$(PREFIX)/lib/systemd/user/hs80d.service"
	$(INSTALL) -D -m 0644 data/systemd/hs80-spatial.service "$(DESTDIR)$(PREFIX)/lib/systemd/user/hs80-spatial.service"
	$(INSTALL) -D -m 0644 data/dbus/io.github.hs80control.Daemon.service "$(DATADIR)/dbus-1/services/io.github.hs80control.Daemon.service"
	$(INSTALL) -D -m 0644 data/applications/io.github.hs80control.App.desktop "$(DATADIR)/applications/io.github.hs80control.App.desktop"
	$(INSTALL) -D -m 0644 data/metainfo/io.github.hs80control.App.metainfo.xml "$(DATADIR)/metainfo/io.github.hs80control.App.metainfo.xml"
	$(INSTALL) -D -m 0644 data/icons/io.github.hs80control.App.svg "$(DATADIR)/icons/hicolor/scalable/apps/io.github.hs80control.App.svg"

install-user: check-home
	$(INSTALL) -d "$(HOME)/.local/lib/hs80-control/hs80_control" "$(HOME)/.local/bin" "$(HOME)/.local/libexec"
	$(INSTALL) -m 0644 src/hs80_control/*.py "$(HOME)/.local/lib/hs80-control/hs80_control/"
	$(INSTALL) -m 0755 bin/hs80-control bin/hs80ctl "$(HOME)/.local/bin/"
	$(INSTALL) -m 0755 bin/hs80d "$(HOME)/.local/libexec/hs80d"
	$(INSTALL) -D -m 0644 data/systemd/hs80d-user-local.service "$(HOME)/.config/systemd/user/hs80d.service"
	$(INSTALL) -D -m 0644 data/systemd/hs80-spatial.service "$(HOME)/.config/systemd/user/hs80-spatial.service"
	$(INSTALL) -D -m 0644 data/dbus/io.github.hs80control.Daemon-user-local.service "$(HOME)/.local/share/dbus-1/services/io.github.hs80control.Daemon.service"
	$(INSTALL) -D -m 0644 data/applications/io.github.hs80control.App.desktop "$(HOME)/.local/share/applications/io.github.hs80control.App.desktop"
	$(INSTALL) -D -m 0644 data/metainfo/io.github.hs80control.App.metainfo.xml "$(HOME)/.local/share/metainfo/io.github.hs80control.App.metainfo.xml"
	$(INSTALL) -D -m 0644 data/icons/io.github.hs80control.App.svg "$(HOME)/.local/share/icons/hicolor/scalable/apps/io.github.hs80control.App.svg"
	systemctl --user daemon-reload
	systemctl --user enable --now hs80d.service

uninstall: check-prefix
	rm -rf "$(LIBDIR)"
	rm -f "$(BINDIR)/hs80-control" "$(BINDIR)/hs80ctl" "$(LIBEXECDIR)/hs80d"
	rm -f "$(DESTDIR)$(PREFIX)/lib/udev/rules.d/70-hs80-control.rules"
	rm -f "$(DESTDIR)$(PREFIX)/lib/systemd/user/hs80d.service" "$(DESTDIR)$(PREFIX)/lib/systemd/user/hs80-spatial.service"
	rm -f "$(DATADIR)/dbus-1/services/io.github.hs80control.Daemon.service"
	rm -f "$(DATADIR)/applications/io.github.hs80control.App.desktop"
	rm -f "$(DATADIR)/metainfo/io.github.hs80control.App.metainfo.xml"
	rm -f "$(DATADIR)/icons/hicolor/scalable/apps/io.github.hs80control.App.svg"

uninstall-user: check-home
	@if command -v systemctl >/dev/null 2>&1; then \
		systemctl --user disable --now hs80d.service hs80-spatial.service >/dev/null 2>&1 || :; \
	fi
	rm -rf "$(HOME)/.local/lib/hs80-control"
	rm -f "$(HOME)/.local/bin/hs80-control" "$(HOME)/.local/bin/hs80ctl" "$(HOME)/.local/libexec/hs80d"
	rm -f "$(HOME)/.config/systemd/user/hs80d.service" "$(HOME)/.config/systemd/user/hs80-spatial.service"
	rm -f "$(HOME)/.local/share/dbus-1/services/io.github.hs80control.Daemon.service"
	rm -f "$(HOME)/.local/share/applications/io.github.hs80control.App.desktop"
	rm -f "$(HOME)/.local/share/metainfo/io.github.hs80control.App.metainfo.xml"
	rm -f "$(HOME)/.local/share/icons/hicolor/scalable/apps/io.github.hs80control.App.svg"
	@if command -v systemctl >/dev/null 2>&1; then systemctl --user daemon-reload >/dev/null 2>&1 || :; fi

clean:
	rm -rf src/hs80_control/__pycache__ tests/__pycache__ build dist

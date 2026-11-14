# Fedora COPR builds the source RPM with this file ("make_srpm" method):
#   make -f .copr/Makefile srpm outdir=<dir> spec=<spec>
# It runs in the cloned repository; mock then builds the binary RPMs.

outdir ?= $(CURDIR)/dist
spec ?= packaging/hs80-control.spec

srpm:
	command -v rpmbuild >/dev/null || dnf -y install rpm-build
	command -v make >/dev/null || dnf -y install make
	$(MAKE) dist
	rpmbuild -bs "$(spec)" \
		--define "_sourcedir $(CURDIR)/dist" \
		--define "_srcrpmdir $(outdir)"

.PHONY: srpm

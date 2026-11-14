# Packaging

| Directory / file | For | Built from |
| :--- | :--- | :--- |
| `hs80-control.spec` | Fedora RPM (`make rpm`, COPR) | `make dist` source archive |
| `../.copr/Makefile` | Fedora COPR, "make_srpm" method | the cloned repository |
| `aur/` | Arch Linux AUR (`PKGBUILD`, `.SRCINFO`, install script) | the source archive attached to the GitHub release |

## Fedora COPR

One-time setup on <https://copr.fedorainfracloud.org> (Fedora account needed):

1. **New project** `hs80-control`, chroots: the supported Fedora releases (`fedora-44-x86_64`, `fedora-45-x86_64`, …). The package is `noarch`, so one architecture is enough.
2. **Packages → New package → SCM**:
   - Clone URL: `https://github.com/ST1CKEL/HS80_Control.git`
   - Committish: the release tag, e.g. `v0.9.0` (or empty for `main`)
   - Spec file: `packaging/hs80-control.spec`
   - Build SRPM with: **make_srpm**
3. **Rebuild**. Users then install with:

   ```bash
   sudo dnf copr enable st1ckel/hs80-control
   sudo dnf install hs80-control
   ```

For automatic builds on every release, enable the GitHub webhook under *Settings → Integrations* of the COPR project.

## Arch Linux AUR

After each release:

1. Set `pkgver` in `aur/PKGBUILD`, reset `pkgrel=1`, and replace `sha256sums` with the digest of the release's `hs80-control-<version>.tar.gz` (`gh release view v<version> --json assets`).
2. Regenerate `.SRCINFO`: `makepkg --printsrcinfo > .SRCINFO`.
3. Push both files and `hs80-control.install` to `ssh://aur@aur.archlinux.org/hs80-control.git` (an AUR account with an SSH key is needed for the first push, which also creates the package).

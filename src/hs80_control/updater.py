"""Find and fetch new releases from the project's GitHub page.

Only the published RPM of the latest release is considered, and only from
github.com over HTTPS. The request carries nothing but a generic client
name. Installing goes through ``pkexec dnf``, so the system's package
manager stays in charge and the desktop asks for the password itself.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import urllib.request


RELEASE_API = "https://api.github.com/repos/ST1CKEL/HS80_Control/releases/latest"
RELEASES_PAGE = "https://github.com/ST1CKEL/HS80_Control/releases/latest"
PACKAGE = "hs80-control"
USER_AGENT = "hs80-control-updater"
MAX_PACKAGE_BYTES = 50 * 1024 * 1024
_ASSET_NAME = re.compile(rf"{PACKAGE}-[0-9][0-9A-Za-z._-]*\.noarch\.rpm")


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    asset_name: str
    asset_url: str
    page_url: str
    sha256: str = ""


def parse_version(text: str) -> tuple[int, ...]:
    """``v0.8.0`` -> ``(0, 8, 0)``; anything unparsable sorts lowest."""

    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", text.strip())
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(candidate: str, current: str) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    return bool(new) and new > old


def parse_release(data: object) -> Release:
    if not isinstance(data, dict):
        raise UpdateError("unexpected answer from GitHub")
    version = str(data.get("tag_name", "")).lstrip("v")
    if not parse_version(version):
        raise UpdateError("the latest release has no version tag")
    page = str(data.get("html_url", "")) or RELEASES_PAGE
    if not page.startswith("https://github.com/"):
        page = RELEASES_PAGE
    for asset in data.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name", ""))
        url = str(asset.get("browser_download_url", ""))
        if _ASSET_NAME.fullmatch(name) and url.startswith("https://github.com/"):
            digest = str(asset.get("digest") or "")
            return Release(
                version=version,
                asset_name=name,
                asset_url=url,
                page_url=page,
                sha256=digest[7:].lower() if digest.startswith("sha256:") else "",
            )
    raise UpdateError("the latest release contains no RPM package")


def _fetch(url: str, timeout: float, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(limit + 1)
    except (OSError, ValueError) as exc:
        raise UpdateError(str(exc)) from exc
    if len(data) > limit:
        raise UpdateError("download is larger than expected")
    return data


def fetch_latest(timeout: float = 15.0) -> Release:
    try:
        data = json.loads(_fetch(RELEASE_API, timeout, 2 * 1024 * 1024))
    except ValueError as exc:
        raise UpdateError("unreadable answer from GitHub") from exc
    return parse_release(data)


def download(release: Release, directory: Path, timeout: float = 60.0) -> Path:
    data = _fetch(release.asset_url, timeout, MAX_PACKAGE_BYTES)
    if release.sha256 and hashlib.sha256(data).hexdigest() != release.sha256:
        raise UpdateError("checksum of the downloaded package does not match")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / release.asset_name
    path.write_bytes(data)
    return path


def install_command(package: Path) -> list[str]:
    return ["pkexec", "dnf", "install", "-y", str(package)]


def is_packaged(module_file: str = __file__) -> bool:
    """True for the RPM installation; a checkout or ~/.local is not ours to
    replace through dnf."""

    return Path(module_file).resolve().is_relative_to("/usr/lib/hs80-control")

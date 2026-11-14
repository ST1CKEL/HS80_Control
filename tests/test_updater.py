import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from hs80_control import updater


def _release(**asset: object) -> dict[str, object]:
    base = {
        "name": "hs80-control-0.9.0-1.fc45.noarch.rpm",
        "browser_download_url": "https://github.com/ST1CKEL/HS80_Control/releases/download/v0.9.0/hs80-control-0.9.0-1.fc45.noarch.rpm",
    }
    base.update(asset)
    return {
        "tag_name": "v0.9.0",
        "html_url": "https://github.com/ST1CKEL/HS80_Control/releases/tag/v0.9.0",
        "assets": [{"name": "hs80-control-0.9.0.tar.gz"}, base],
    }


class VersionTests(unittest.TestCase):
    def test_versions_compare_numerically(self) -> None:
        self.assertTrue(updater.is_newer("0.10.0", "0.9.9"))
        self.assertTrue(updater.is_newer("v1.0", "0.9.9"))
        self.assertFalse(updater.is_newer("0.8.0", "0.8.0"))
        self.assertFalse(updater.is_newer("0.7.1", "0.8.0"))

    def test_garbage_is_never_newer(self) -> None:
        self.assertFalse(updater.is_newer("latest", "0.8.0"))
        self.assertFalse(updater.is_newer("", "0.8.0"))


class ReleaseParsingTests(unittest.TestCase):
    def test_package_asset_is_selected(self) -> None:
        release = updater.parse_release(_release(digest="sha256:ABCDEF"))
        self.assertEqual("0.9.0", release.version)
        self.assertEqual("hs80-control-0.9.0-1.fc45.noarch.rpm", release.asset_name)
        self.assertEqual("abcdef", release.sha256)

    def test_foreign_download_host_is_refused(self) -> None:
        with self.assertRaises(updater.UpdateError):
            updater.parse_release(
                _release(browser_download_url="https://example.org/x.rpm")
            )

    def test_asset_name_cannot_leave_the_download_directory(self) -> None:
        with self.assertRaises(updater.UpdateError):
            updater.parse_release(_release(name="../hs80-control-1.noarch.rpm"))

    def test_release_without_package_or_tag_is_an_error(self) -> None:
        for data in ({"tag_name": "v0.9.0", "assets": []}, {"assets": []}, []):
            with self.assertRaises(updater.UpdateError):
                updater.parse_release(data)


class DownloadTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def _download(self, payload: bytes, sha256: str) -> Path:
        release = updater.Release("0.9.0", "hs80-control-0.9.0-1.noarch.rpm", "https://github.com/x", "https://github.com/y", sha256)
        with mock.patch.object(updater, "_fetch", return_value=payload):
            return updater.download(release, self.directory)

    def test_matching_checksum_is_accepted(self) -> None:
        path = self._download(b"package", hashlib.sha256(b"package").hexdigest())
        self.assertEqual(b"package", path.read_bytes())

    def test_wrong_checksum_is_refused_and_nothing_is_kept(self) -> None:
        with self.assertRaises(updater.UpdateError):
            self._download(b"tampered", hashlib.sha256(b"package").hexdigest())
        self.assertEqual([], list(self.directory.iterdir()))

    def test_install_runs_dnf_through_pkexec(self) -> None:
        self.assertEqual(
            ["pkexec", "dnf", "install", "-y", "/tmp/a.rpm"],
            updater.install_command(Path("/tmp/a.rpm")),
        )

    def test_only_the_rpm_installation_updates_itself(self) -> None:
        self.assertTrue(
            updater.is_packaged("/usr/lib/hs80-control/hs80_control/updater.py")
        )
        self.assertFalse(
            updater.is_packaged("/home/u/.local/lib/hs80-control/hs80_control/updater.py")
        )


if __name__ == "__main__":
    unittest.main()

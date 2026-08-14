import unittest

from app.version import application_version


class VersionTests(unittest.TestCase):
    def test_packaged_version_matches_release_candidate(self):
        self.assertEqual(application_version(), "1.0.0-rc.1")


if __name__ == "__main__":
    unittest.main()

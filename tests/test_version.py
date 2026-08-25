import unittest

from app.version import application_version


class VersionTests(unittest.TestCase):
    def test_packaged_version_matches_stable_release(self):
        self.assertEqual(application_version(), "1.0.2")


if __name__ == "__main__":
    unittest.main()

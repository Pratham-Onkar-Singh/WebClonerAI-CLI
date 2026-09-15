import unittest
from unittest.mock import Mock, patch

from webcloner.runner import ContainerRunner


class RunnerTests(unittest.TestCase):
    def test_cleanup_auto_remove_race(self):
        removing = Mock(returncode=1, stderr=b"removal of container is already in progress")
        absent = Mock(returncode=1, stderr=b"Error: No such container: fixture")
        with patch("webcloner.runner.subprocess.run", side_effect=[removing, absent]) as run:
            ContainerRunner._cleanup("docker", "fixture", {})
            self.assertEqual(run.call_count, 2)

    def test_disabled_without_image(self):
        with patch("subprocess.Popen") as popen, self.assertRaises(RuntimeError):
            ContainerRunner(None).run(Mock(), "index.html")
        popen.assert_not_called()

    def test_no_runtime_no_host_fallback(self):
        with patch("webcloner.runner.shutil.which", return_value=None), patch("subprocess.Popen") as popen:
            with self.assertRaises(RuntimeError):
                ContainerRunner("fixture@sha256:" + "0" * 64).run(Mock(), "index.html")
            popen.assert_not_called()

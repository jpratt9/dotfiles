"""Unit tests for scripts/write_deploy_sh.py. No external calls — pure file write."""
import importlib.util
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "write_deploy_sh.py")

spec = importlib.util.spec_from_file_location("write_deploy_sh", SCRIPT)
wds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wds)


def run_main(argv):
    with mock.patch.object(sys, "argv", argv):
        wds.main()


class WriteDeployShTests(unittest.TestCase):
    def test_writes_executable_script_with_project_and_name(self):
        with tempfile.TemporaryDirectory() as d:
            run_main(["prog", "--project", "aphlandscape",
                      "--name", "APH Landscape", "--dir", d])
            path = os.path.join(d, "deploy.sh")
            self.assertTrue(os.path.exists(path))
            self.assertTrue(os.stat(path).st_mode & stat.S_IXUSR, "must be chmod +x")
            with open(path) as f:
                body = f.read()
            self.assertIn('PROJECT="aphlandscape"', body)
            self.assertIn("APH Landscape site", body)          # human name in comment
            self.assertIn("wrangler pages deploy public", body)
            self.assertIn("--project-name=", body)
            self.assertTrue(body.startswith("#!/usr/bin/env bash"))

    def test_name_defaults_to_project_when_omitted(self):
        with tempfile.TemporaryDirectory() as d:
            run_main(["prog", "--project", "joescafe", "--dir", d])
            with open(os.path.join(d, "deploy.sh")) as f:
                body = f.read()
            self.assertIn("joescafe site", body)

    def test_expands_user_in_dir(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(wds.os.path, "expanduser", return_value=d) as m:
                run_main(["prog", "--project", "x", "--dir", "~/dev/x"])
                m.assert_called_with("~/dev/x")
            self.assertTrue(os.path.exists(os.path.join(d, "deploy.sh")))

    def test_no_unrendered_placeholders(self):
        with tempfile.TemporaryDirectory() as d:
            run_main(["prog", "--project", "x", "--name", "X", "--dir", d])
            with open(os.path.join(d, "deploy.sh")) as f:
                body = f.read()
            # bash uses ${PROJECT}; ensure no leftover python format braces
            self.assertNotIn("{project}", body)
            self.assertNotIn("{name}", body)
            self.assertIn("${PROJECT}", body)


if __name__ == "__main__":
    unittest.main()

"""Unit tests for scripts/write_deploy_sh.py. No external calls — pure file write."""
import importlib.util
import os
import stat
import subprocess
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
            self.assertNotIn("{turnstile}", body)
            self.assertIn("${PROJECT}", body)


class TurnstileStepTests(unittest.TestCase):
    """deploy.sh must run the Turnstile injector before uploading."""

    def _body(self, d):
        run_main(["prog", "--project", "x", "--name", "X", "--dir", d])
        with open(os.path.join(d, "deploy.sh")) as f:
            return f.read()

    def test_injector_is_invoked_with_an_absolute_path(self):
        with tempfile.TemporaryDirectory() as d:
            body = self._body(d)
            expected = os.path.join(
                os.path.dirname(os.path.abspath(wds.__file__)), "ensure_turnstile.py")
            self.assertIn(f'TURNSTILE="{expected}"', body)
            self.assertTrue(os.path.isabs(expected))
            self.assertIn('python3 "$TURNSTILE" --dir public', body)

    def test_runs_before_the_upload(self):
        with tempfile.TemporaryDirectory() as d:
            body = self._body(d)
            self.assertLess(body.index('python3 "$TURNSTILE"'),
                            body.index("wrangler pages deploy public"),
                            "markup must be injected before the files are uploaded")

    def test_step_is_skipped_when_skill_absent(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIn('if [ -f "$TURNSTILE" ]; then', self._body(d))

    def test_exit_2_tolerated_other_failures_abort(self):
        with tempfile.TemporaryDirectory() as d:
            body = self._body(d)
            self.assertIn("[ $ts_rc -ne 0 ] && [ $ts_rc -ne 2 ]", body)
            self.assertIn("exit $ts_rc", body)

    def test_generated_script_is_valid_bash(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "deploy.sh")
            run_main(["prog", "--project", "x", "--name", "X", "--dir", d])
            proc = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, f"bash syntax error: {proc.stderr}")


if __name__ == "__main__":
    unittest.main()

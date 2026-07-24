"""Unit tests for scripts/formbackend_form.py.

All FormBackend API calls are MOCKED — no real forms are created.
"""
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "formbackend_form.py")

spec = importlib.util.spec_from_file_location("formbackend_form", SCRIPT)
fb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fb)

FULL_ENV = {
    "FORMBACKEND_TOKEN": "tok123",
    "TURNSTILE_SITEKEY": "sk-1",
    "TURNSTILE_SECRET": "sec-1",
}


class FormbackendFormTests(unittest.TestCase):
    def setUp(self):
        """The form name comes from the cwd's folder name, so run each test from
        inside a throwaway dir called `genzhaulers`."""
        self._prev_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        proj = os.path.join(self._tmp.name, "genzhaulers")
        os.mkdir(proj)
        os.chdir(proj)

    def tearDown(self):
        os.chdir(self._prev_cwd)
        self._tmp.cleanup()

    def run_main(self, argv_extra, env_vals):
        out = io.StringIO()
        with mock.patch.object(fb, "env", return_value=env_vals), \
                mock.patch.object(sys, "argv", ["formbackend_form.py"] + argv_extra), \
                mock.patch.object(sys, "stdout", out):
            fb.main()
        return json.loads(out.getvalue())

    def test_missing_token_exits_3(self):
        with mock.patch.object(fb, "env", return_value={}), \
                mock.patch.object(sys, "argv", ["formbackend_form.py"]):
            with self.assertRaises(SystemExit) as cm:
                fb.main()
        self.assertEqual(cm.exception.code, 3)

    def test_create_failure_exits_4(self):
        with mock.patch.object(fb, "call", lambda m, u, t, p=None: (422, {})), \
                mock.patch.object(fb, "env", return_value=FULL_ENV), \
                mock.patch.object(sys, "argv", ["formbackend_form.py"]):
            with self.assertRaises(SystemExit) as cm:
                fb.main()
        self.assertEqual(cm.exception.code, 4)

    def test_email_and_turnstile_stick_no_todos(self):
        def fake_call(method, url, token, payload=None):
            if method == "POST":
                self.assertEqual(payload["form"]["name"], "genzhaulers")
                self.assertEqual(payload["form"]["notify_owner_emails"], "c@x.com")
                self.assertEqual(payload["form"]["cloudflare_turnstile_sitekey"], "sk-1")
                return 201, {"identifier": "abc123"}
            if method == "PATCH":
                return 200, {}
            if method == "GET":
                return 200, {"identifier": "abc123", "notify_owner_emails": "c@x.com"}
            raise AssertionError(method)

        with mock.patch.object(fb, "call", fake_call):
            out = self.run_main(["--email", "c@x.com"], FULL_ENV)
        self.assertEqual(out["identifier"], "abc123")
        self.assertEqual(out["endpoint"], "https://www.formbackend.com/f/abc123")
        self.assertEqual(out["dashboard_todo"], [])
        self.assertEqual(out["patch_http"], 200)

    def test_api_refuses_extras_reports_todos(self):
        def fake_call(method, url, token, payload=None):
            if method == "POST":
                return 201, {"identifier": "abc123"}
            if method == "PATCH":
                return 404, {}
            if method == "GET":
                return 200, {"identifier": "abc123", "notify_owner_emails": None}
            raise AssertionError(method)

        with mock.patch.object(fb, "call", fake_call):
            out = self.run_main(["--email", "c@x.com"], FULL_ENV)
        self.assertIn("set notification email", out["dashboard_todo"])
        self.assertIn("paste Turnstile sitekey+secret in form Settings", out["dashboard_todo"])

    def test_no_email_no_turnstile_skips_patch(self):
        calls = []

        def fake_call(method, url, token, payload=None):
            calls.append(method)
            if method == "POST":
                self.assertEqual(payload, {"form": {"name": "genzhaulers"}})
                return 201, {"identifier": "abc123"}
            if method == "GET":
                return 200, {"identifier": "abc123"}
            raise AssertionError(method)

        env_vals = {"FORMBACKEND_TOKEN": "tok123"}
        with mock.patch.object(fb, "call", fake_call):
            out = self.run_main([], env_vals)
        self.assertNotIn("PATCH", calls)
        self.assertIsNone(out["patch_http"])
        self.assertEqual(out["dashboard_todo"], [])


if __name__ == "__main__":
    unittest.main()

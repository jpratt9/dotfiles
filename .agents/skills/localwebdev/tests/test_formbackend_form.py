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

    def run_main(self, env_vals):
        """The script takes no arguments and touches no Cloudflare API."""
        out = io.StringIO()
        with mock.patch.object(fb, "env", return_value=env_vals), \
                mock.patch.object(sys, "argv", ["formbackend_form.py"]), \
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

    def test_reuses_existing_form_never_duplicates(self):
        """The whole point of idempotency: a rerun must NOT create a second form."""
        posted = []

        def fake_call(method, url, token, payload=None):
            if method == "POST":
                posted.append(payload)
                return 201, {"identifier": "should-not-happen"}
            if method == "GET" and url.endswith("/forms"):
                return 200, {"forms": [{"name": "genzhaulers", "identifier": "old123"}]}
            if method == "GET":
                return 200, {"identifier": "old123", "notify_owner_emails": "a@b.com",
                             "notify_owner_on_submission": True,
                             "cloudflare_turnstile_sitekey": "0xSITE"}
            raise AssertionError(method)

        with mock.patch.object(fb, "call", fake_call):
            out = self.run_main(FULL_ENV)
        self.assertEqual(posted, [], "reran and created a duplicate form")
        self.assertTrue(out["reused_existing_form"])
        self.assertEqual(out["identifier"], "old123")
        self.assertEqual(out["endpoint"], "https://www.formbackend.com/f/old123")
        self.assertEqual(out["blocking_dashboard_actions"], [])

    def test_creates_when_absent_and_uses_folder_name(self):
        posted = []

        def fake_call(method, url, token, payload=None):
            if method == "POST":
                posted.append(payload)
                return 201, {"identifier": "new123"}
            if method == "GET" and url.endswith("/forms"):
                return 200, {"forms": [{"name": "someone-else", "identifier": "x"}]}
            if method == "GET":
                return 200, {"identifier": "new123", "notify_owner_emails": "a@b.com",
                             "notify_owner_on_submission": True,
                             "cloudflare_turnstile_sitekey": "0xSITE"}
            raise AssertionError(method)

        with mock.patch.object(fb, "call", fake_call):
            out = self.run_main(FULL_ENV)
        self.assertEqual(posted[0]["form"]["name"], "genzhaulers")
        self.assertFalse(out["reused_existing_form"])

    def test_create_sends_only_the_name(self):
        """No undocumented turnstile extras — they were ignored by FormBackend
        and are the prime suspect for the original 403."""
        posted = []

        def fake_call(method, url, token, payload=None):
            if method == "POST":
                posted.append(payload)
                return 201, {"identifier": "new123"}
            if method == "GET" and url.endswith("/forms"):
                return 200, {"forms": []}
            if method == "GET":
                return 200, {"identifier": "new123", "notify_owner_emails": "a@b.com",
                             "notify_owner_on_submission": True}
            raise AssertionError(method)

        with mock.patch.object(fb, "call", fake_call):
            out = self.run_main(FULL_ENV)
        self.assertEqual(posted, [{"form": {"name": "genzhaulers"}}])
        self.assertEqual(out["identifier"], "new123")

    def test_find_form_handles_bare_list_response(self):
        """The API returns {"forms": [...]}, but tolerate a bare list too."""
        with mock.patch.object(fb, "call", lambda m, u, t, p=None:
                               (200, [{"name": "genzhaulers", "identifier": "list123"}])):
            self.assertEqual(fb.find_form("genzhaulers", "tok")["identifier"], "list123")
            self.assertIsNone(fb.find_form("nope", "tok"))

    def test_find_form_returns_none_on_api_error(self):
        with mock.patch.object(fb, "call", lambda m, u, t, p=None: (500, {})):
            self.assertIsNone(fb.find_form("genzhaulers", "tok"))

    def test_notifications_off_is_blocking(self):
        def fake_call(method, url, token, payload=None):
            if method == "GET" and url.endswith("/forms"):
                return 200, {"forms": [{"name": "genzhaulers", "identifier": "old123"}]}
            if method == "GET":
                return 200, {"identifier": "old123", "notify_owner_emails": None,
                             "notify_owner_on_submission": False}
            raise AssertionError(method)

        with mock.patch.object(fb, "call", fake_call):
            out = self.run_main({"FORMBACKEND_TOKEN": "tok123"})
        acts = " ".join(out["blocking_dashboard_actions"])
        self.assertIn("notify owner on submission", acts)
        self.assertIn("notification email", acts)


if __name__ == "__main__":
    unittest.main()

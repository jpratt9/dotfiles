"""Unit tests for scripts/turnstile_widget.py.

All Cloudflare API calls are MOCKED — no real widgets are touched.
"""
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "turnstile_widget.py")

spec = importlib.util.spec_from_file_location("turnstile_widget", SCRIPT)
tw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tw)

BASE_ENV = (
    "WEB3FORMS_ACCESS_KEY=zzz\n"
    "FORMBACKEND_TOKEN=\n"
    "TURNSTILE_SITEKEY={sitekey}\n"
    "TURNSTILE_SECRET={secret}\n"
    "CLOUDFLARE_ACCOUNT_ID=acct123\n"
    "CLOUDFLARE_API_TOKEN=tok123\n"
)


class TurnstileWidgetTests(unittest.TestCase):
    def setUp(self):
        fd, self.env_file = tempfile.mkstemp(suffix=".env")
        os.close(fd)
        self.addCleanup(os.unlink, self.env_file)
        self._env_patch = mock.patch.object(tw, "ENV_PATH", Path(self.env_file))
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

    def write_env(self, sitekey="", secret=""):
        Path(self.env_file).write_text(BASE_ENV.format(sitekey=sitekey, secret=secret))

    def run_main(self, hostname="new.pages.dev"):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["turnstile_widget.py", "--hostname", hostname]), \
                mock.patch.object(sys, "stdout", out):
            tw.main()
        return json.loads(out.getvalue())

    def test_env_parses_file(self):
        self.write_env(sitekey="sk-1", secret="sec-1")
        vals = tw.env()
        self.assertEqual(vals["TURNSTILE_SITEKEY"], "sk-1")
        self.assertEqual(vals["CLOUDFLARE_ACCOUNT_ID"], "acct123")

    def test_save_env_keys_rewrites_only_turnstile_lines(self):
        self.write_env(sitekey="old-sk", secret="old-sec")
        tw.save_env_keys("new-sk", "new-sec")
        text = Path(self.env_file).read_text()
        self.assertIn("TURNSTILE_SITEKEY=new-sk", text)
        self.assertIn("TURNSTILE_SECRET=new-sec", text)
        self.assertIn("WEB3FORMS_ACCESS_KEY=zzz", text)
        self.assertIn("CLOUDFLARE_API_TOKEN=tok123", text)

    def test_missing_token_exits_3(self):
        Path(self.env_file).write_text("CLOUDFLARE_ACCOUNT_ID=acct123\n")
        with mock.patch.object(sys, "argv", ["turnstile_widget.py", "--hostname", "x.dev"]):
            with self.assertRaises(SystemExit) as cm:
                tw.main()
        self.assertEqual(cm.exception.code, 3)

    def test_appends_to_existing_widget(self):
        self.write_env(sitekey="sk-1", secret="sec-1")
        widget = {"result": {"name": "client-sites-01", "mode": "managed",
                             "domains": ["a.pages.dev"]}}
        calls = []

        def fake_call(method, url, token, payload=None):
            calls.append((method, url, payload))
            if method == "GET":
                return 200, widget
            if method == "PUT":
                return 200, {"result": {}}
            raise AssertionError(method)

        with mock.patch.object(tw, "call", fake_call):
            out = self.run_main("new.pages.dev")
        self.assertEqual(out["action"], "appended")
        self.assertEqual(out["hostnames_used"], 2)
        put = [c for c in calls if c[0] == "PUT"][0]
        self.assertEqual(put[2]["domains"], ["a.pages.dev", "new.pages.dev"])

    def test_already_present_is_noop(self):
        self.write_env(sitekey="sk-1", secret="sec-1")
        widget = {"result": {"name": "client-sites-01", "mode": "managed",
                             "domains": ["new.pages.dev"]}}
        with mock.patch.object(tw, "call", lambda m, u, t, p=None: (200, widget)):
            out = self.run_main("new.pages.dev")
        self.assertEqual(out["action"], "already-present")

    def test_full_widget_creates_next_and_updates_env(self):
        self.write_env(sitekey="sk-1", secret="sec-1")
        full = {"result": {"name": "client-sites-01", "mode": "managed",
                           "domains": [f"c{i}.dev" for i in range(tw.MAX_HOSTNAMES)]}}
        listing = {"result": [{"name": "client-sites-01"}]}
        created = {"result": {"name": "client-sites-02", "sitekey": "sk-2", "secret": "sec-2"}}

        def fake_call(method, url, token, payload=None):
            if method == "GET" and url.endswith("/sk-1"):
                return 200, full
            if method == "GET":
                return 200, listing
            if method == "POST":
                self.assertEqual(payload["name"], "client-sites-02")
                self.assertEqual(payload["domains"], ["new.pages.dev"])
                return 200, created
            raise AssertionError(method)

        with mock.patch.object(tw, "call", fake_call):
            out = self.run_main("new.pages.dev")
        self.assertEqual(out["action"], "created")
        self.assertTrue(out["env_updated"])
        text = Path(self.env_file).read_text()
        self.assertIn("TURNSTILE_SITEKEY=sk-2", text)
        self.assertIn("TURNSTILE_SECRET=sec-2", text)

    def test_no_existing_sitekey_creates_first_widget(self):
        self.write_env()  # blank keys
        listing = {"result": []}
        created = {"result": {"name": "client-sites-01", "sitekey": "sk-1", "secret": "sec-1"}}

        def fake_call(method, url, token, payload=None):
            if method == "GET":
                return 200, listing
            if method == "POST":
                self.assertEqual(payload["name"], "client-sites-01")
                return 200, created
            raise AssertionError(method)

        with mock.patch.object(tw, "call", fake_call):
            out = self.run_main("first.pages.dev")
        self.assertEqual(out["action"], "created")

    def test_create_failure_exits_4(self):
        self.write_env()
        with mock.patch.object(tw, "call", lambda m, u, t, p=None: (403, {"errors": ["nope"]})), \
                mock.patch.object(sys, "argv", ["turnstile_widget.py", "--hostname", "x.dev"]):
            with self.assertRaises(SystemExit) as cm:
                tw.main()
        self.assertEqual(cm.exception.code, 4)


if __name__ == "__main__":
    unittest.main()

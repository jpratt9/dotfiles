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


def listing(*widgets):
    return {"result": [dict(w) for w in widgets]}


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

    def env_text(self):
        return Path(self.env_file).read_text()

    def run_main(self, hostname="new.pages.dev"):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["turnstile_widget.py", "--hostname", hostname]), \
                mock.patch.object(sys, "stdout", out):
            tw.main()
        return json.loads(out.getvalue())

    # ---------- helpers / plumbing ----------

    def test_env_parses_file(self):
        self.write_env(sitekey="sk-1", secret="sec-1")
        vals = tw.env()
        self.assertEqual(vals["TURNSTILE_SITEKEY"], "sk-1")
        self.assertEqual(vals["CLOUDFLARE_ACCOUNT_ID"], "acct123")

    def test_save_env_keys_rewrites_only_turnstile_lines(self):
        self.write_env(sitekey="old-sk", secret="old-sec")
        tw.save_env_keys("new-sk", "new-sec")
        text = self.env_text()
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

    def test_list_failure_exits_4(self):
        self.write_env()
        with mock.patch.object(tw, "call", lambda m, u, t, p=None: (500, {})), \
                mock.patch.object(sys, "argv", ["turnstile_widget.py", "--hostname", "x.dev"]):
            with self.assertRaises(SystemExit) as cm:
                tw.main()
        self.assertEqual(cm.exception.code, 4)

    # ---------- 1) hostname already covered ----------

    def test_already_present_on_env_widget(self):
        self.write_env(sitekey="sk-1", secret="sec-1")
        w = {"sitekey": "sk-1", "name": "client-sites-01", "mode": "managed",
             "domains": ["new.pages.dev"]}
        with mock.patch.object(tw, "call", lambda m, u, t, p=None: (200, listing(w))):
            out = self.run_main("new.pages.dev")
        self.assertEqual(out["action"], "already-present")
        self.assertFalse(out["env_updated"])

    def test_already_present_on_foreign_widget_syncs_env_when_secret_known(self):
        self.write_env(sitekey="sk-1", secret="sec-1")
        w = {"sitekey": "sk-9", "secret": "sec-9", "name": "manual-widget",
             "mode": "managed", "domains": ["new.pages.dev"]}
        with mock.patch.object(tw, "call", lambda m, u, t, p=None: (200, listing(w))):
            out = self.run_main("new.pages.dev")
        self.assertEqual(out["action"], "already-present")
        self.assertTrue(out["env_updated"])
        self.assertIn("TURNSTILE_SITEKEY=sk-9", self.env_text())

    # ---------- 2) append to a widget with room ----------

    def test_appends_to_env_widget(self):
        self.write_env(sitekey="sk-1", secret="sec-1")
        w = {"sitekey": "sk-1", "name": "client-sites-01", "mode": "managed",
             "domains": ["a.pages.dev"]}
        puts = []

        def fake_call(method, url, token, payload=None):
            if method == "GET":
                return 200, listing(w)
            if method == "PUT":
                puts.append((url, payload))
                return 200, {"result": {}}
            raise AssertionError(method)

        with mock.patch.object(tw, "call", fake_call):
            out = self.run_main("new.pages.dev")
        self.assertEqual(out["action"], "appended")
        self.assertEqual(out["hostnames_used"], 2)
        self.assertEqual(puts[0][1]["domains"], ["a.pages.dev", "new.pages.dev"])

    def test_prefers_env_widget_over_other_candidates(self):
        self.write_env(sitekey="sk-1", secret="sec-1")
        other = {"sitekey": "sk-9", "secret": "sec-9", "name": "client-sites-02",
                 "mode": "managed", "domains": []}
        mine = {"sitekey": "sk-1", "name": "client-sites-01", "mode": "managed",
                "domains": ["a.pages.dev"]}

        def fake_call(method, url, token, payload=None):
            if method == "GET":
                return 200, listing(other, mine)
            if method == "PUT":
                self.assertIn("sk-1", url)
                return 200, {"result": {}}
            raise AssertionError(method)

        with mock.patch.object(tw, "call", fake_call):
            out = self.run_main("new.pages.dev")
        self.assertEqual(out["sitekey"], "sk-1")
        self.assertFalse(out["env_updated"])

    def test_append_refused_falls_back_to_create(self):
        # account hard-capped below MAX_HOSTNAMES: PUT fails, script must create
        self.write_env(sitekey="sk-1", secret="sec-1")
        w = {"sitekey": "sk-1", "name": "client-sites-01", "mode": "managed",
             "domains": [f"c{i}.dev" for i in range(10)]}
        created = {"result": {"name": "client-sites-02", "sitekey": "sk-2", "secret": "sec-2"}}

        def fake_call(method, url, token, payload=None):
            if method == "GET":
                return 200, listing(w)
            if method == "PUT":
                return 400, {"errors": ["hostname limit"]}
            if method == "POST":
                return 200, created
            raise AssertionError(method)

        with mock.patch.object(tw, "call", fake_call):
            out = self.run_main("new.pages.dev")
        self.assertEqual(out["action"], "created")
        self.assertIn("TURNSTILE_SITEKEY=sk-2", self.env_text())

    def test_foreign_widget_without_secret_is_skipped(self):
        # spare room on a widget whose secret we can't learn → create instead
        self.write_env()  # no env keys at all
        w = {"sitekey": "sk-9", "name": "client-sites-01", "mode": "managed", "domains": []}
        created = {"result": {"name": "client-sites-02", "sitekey": "sk-2", "secret": "sec-2"}}
        puts = []

        def fake_call(method, url, token, payload=None):
            if method == "GET" and "?" in url:
                return 200, listing(w)
            if method == "GET":
                return 200, {"result": w}  # detail fetch still has no secret
            if method == "PUT":
                puts.append(url)
                return 200, {"result": {}}
            if method == "POST":
                return 200, created
            raise AssertionError(method)

        with mock.patch.object(tw, "call", fake_call):
            out = self.run_main("new.pages.dev")
        self.assertEqual(out["action"], "created")
        self.assertEqual(puts, [])

    # ---------- 3) create ----------

    def test_full_env_widget_rolls_over_to_new_widget(self):
        self.write_env(sitekey="sk-1", secret="sec-1")
        full = {"sitekey": "sk-1", "name": "client-sites-01", "mode": "managed",
                "domains": [f"c{i}.dev" for i in range(tw.MAX_HOSTNAMES)]}
        created = {"result": {"name": "client-sites-02", "sitekey": "sk-2", "secret": "sec-2"}}

        def fake_call(method, url, token, payload=None):
            if method == "GET":
                return 200, listing(full)
            if method == "POST":
                self.assertEqual(payload["name"], "client-sites-02")
                self.assertEqual(payload["domains"], ["new.pages.dev"])
                return 200, created
            raise AssertionError(method)

        with mock.patch.object(tw, "call", fake_call):
            out = self.run_main("new.pages.dev")
        self.assertEqual(out["action"], "created")
        self.assertTrue(out["env_updated"])
        self.assertIn("TURNSTILE_SECRET=sec-2", self.env_text())

    def test_empty_account_creates_first_widget(self):
        self.write_env()

        def fake_call(method, url, token, payload=None):
            if method == "GET":
                return 200, listing()
            if method == "POST":
                self.assertEqual(payload["name"], "client-sites-01")
                self.assertEqual(payload["mode"], "managed")
                return 200, {"result": {"name": "client-sites-01",
                                        "sitekey": "sk-1", "secret": "sec-1"}}
            raise AssertionError(method)

        with mock.patch.object(tw, "call", fake_call):
            out = self.run_main("first.pages.dev")
        self.assertEqual(out["action"], "created")
        self.assertIn("TURNSTILE_SITEKEY=sk-1", self.env_text())

    def test_create_failure_exits_4(self):
        self.write_env()

        def fake_call(method, url, token, payload=None):
            if method == "GET":
                return 200, listing()
            return 403, {"errors": ["nope"]}

        with mock.patch.object(tw, "call", fake_call), \
                mock.patch.object(sys, "argv", ["turnstile_widget.py", "--hostname", "x.dev"]):
            with self.assertRaises(SystemExit) as cm:
                tw.main()
        self.assertEqual(cm.exception.code, 4)


if __name__ == "__main__":
    unittest.main()

"""Unit tests for scripts/verify_site.py.

No real Chrome and no real sockets — the browser layer is mocked everywhere.
"""
import importlib.util
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "verify_site.py")

spec = importlib.util.spec_from_file_location("verify_site", SCRIPT)
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)


def make_project(page="index.html", body="<html></html>"):
    """A temp project dir laid out like a real build. Caller cleans up."""
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "public"), exist_ok=True)
    with open(os.path.join(d, "public", page), "w") as f:
        f.write(body)
    return d


# --------------------------------------------------------------------------
# WebSocket framing
# --------------------------------------------------------------------------

class FrameTests(unittest.TestCase):
    def test_client_frames_are_masked(self):
        frame = vs.encode_frame("hi")
        self.assertTrue(frame[1] & 0x80, "RFC 6455 requires clients to mask")

    def test_roundtrip_small_payload(self):
        fin, opcode, data, rest = vs.decode_frame(vs.encode_frame("hello"))
        self.assertTrue(fin)
        self.assertEqual(opcode, 1)
        self.assertEqual(data, b"hello")
        self.assertEqual(rest, b"")

    def test_roundtrip_16bit_length(self):
        payload = "x" * 1000                     # needs the 126 + uint16 path
        _, _, data, _ = vs.decode_frame(vs.encode_frame(payload))
        self.assertEqual(data, payload.encode())

    def test_roundtrip_64bit_length(self):
        payload = "y" * 70000                    # needs the 127 + uint64 path
        _, _, data, _ = vs.decode_frame(vs.encode_frame(payload))
        self.assertEqual(data, payload.encode())

    def test_decode_returns_none_when_incomplete(self):
        frame = vs.encode_frame("hello")
        self.assertIsNone(vs.decode_frame(frame[:1]))
        self.assertIsNone(vs.decode_frame(frame[:4]))

    def test_decode_leaves_trailing_bytes(self):
        buf = vs.encode_frame("a") + vs.encode_frame("b")
        _, _, data, rest = vs.decode_frame(buf)
        self.assertEqual(data, b"a")
        _, _, data2, rest2 = vs.decode_frame(rest)
        self.assertEqual(data2, b"b")
        self.assertEqual(rest2, b"")

    def test_decodes_unmasked_server_frame(self):
        # servers send unmasked; build one by hand
        payload = b"srv"
        raw = bytes([0x81, len(payload)]) + payload
        fin, opcode, data, rest = vs.decode_frame(raw)
        self.assertTrue(fin)
        self.assertEqual(data, b"srv")
        self.assertEqual(rest, b"")

    def test_continuation_frames_reassemble(self):
        """recv() must join a fragmented text message."""
        first = bytes([0x01, 2]) + b"he"          # FIN=0, opcode=text
        cont = bytes([0x80, 3]) + b"llo"          # FIN=1, opcode=continuation
        ws = vs.WebSocket.__new__(vs.WebSocket)
        ws.buf = first + cont
        ws.sock = mock.Mock()
        self.assertEqual(ws.recv(), "hello")

    def test_ping_is_ponged_and_skipped(self):
        ping = bytes([0x89, 0])                   # opcode 9, empty
        text = bytes([0x81, 2]) + b"ok"
        ws = vs.WebSocket.__new__(vs.WebSocket)
        ws.buf = ping + text
        ws.sock = mock.Mock()
        self.assertEqual(ws.recv(), "ok")
        ws.sock.sendall.assert_called_once()
        sent = ws.sock.sendall.call_args[0][0]
        self.assertEqual(sent[0] & 0x0F, 0xA, "must reply with a pong")

    def test_close_frame_raises(self):
        ws = vs.WebSocket.__new__(vs.WebSocket)
        ws.buf = bytes([0x88, 0])
        ws.sock = mock.Mock()
        with self.assertRaises(ConnectionError):
            ws.recv()

    def test_rejects_non_ws_scheme(self):
        with self.assertRaises(ValueError):
            vs.WebSocket("http://127.0.0.1:9/devtools/page/x")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

class ViewportTests(unittest.TestCase):
    def test_parses(self):
        self.assertEqual(vs.parse_viewport("390x844"), (390, 844))
        self.assertEqual(vs.parse_viewport("1440X900"), (1440, 900))

    def test_rejects_garbage(self):
        for bad in ["", "390", "axb", "390x", "-1x10", "0x0"]:
            with self.assertRaises(ValueError, msg=bad):
                vs.parse_viewport(bad)


class FindChromeTests(unittest.TestCase):
    def test_env_override_wins(self):
        self.assertEqual(vs.find_chrome({"CHROME_PATH": "/custom/chrome"}), "/custom/chrome")

    def test_returns_none_when_nothing_found(self):
        with mock.patch.object(vs.os.path, "exists", return_value=False), \
             mock.patch.object(vs.shutil, "which", return_value=None):
            self.assertIsNone(vs.find_chrome({}))

    def test_finds_absolute_candidate(self):
        target = vs.CHROME_CANDIDATES[0]
        with mock.patch.object(vs.os.path, "exists", side_effect=lambda p: p == target):
            self.assertEqual(vs.find_chrome({}), target)


class SummarizeTests(unittest.TestCase):
    def test_all_clean_passes(self):
        reports = [{"viewport": {"w": 390, "h": 844}, "failures": {}},
                   {"viewport": {"w": 1440, "h": 900}, "failures": {}}]
        self.assertEqual(vs.summarize(reports), (True, 0))

    def test_counts_failures_across_viewports(self):
        reports = [
            {"viewport": {"w": 390, "h": 844},
             "failures": {"overflow": {"elements": []}, "hero_fold": []}},
            {"viewport": {"w": 1440, "h": 900}, "failures": {"zero_size_images": []}},
        ]
        ok, n = vs.summarize(reports)
        self.assertFalse(ok)
        self.assertEqual(n, 3)

    def test_render_marks_ok_and_fail(self):
        lines = vs.render([
            {"viewport": {"w": 390, "h": 844}, "failures": {}},
            {"viewport": {"w": 1440, "h": 900},
             "failures": {"hero_fold": [{"el": "div.x", "bottom": 950}]}},
        ])
        joined = "\n".join(lines)
        self.assertIn("OK   390x844", joined)
        self.assertIn("FAIL 1440x900", joined)
        self.assertIn("hero_fold", joined)


class ProbeSourceTests(unittest.TestCase):
    """The probe is a string, so guard its contract here."""

    def test_awaits_fonts_and_images_before_measuring(self):
        self.assertIn("document.fonts.ready", vs.PROBE_JS)
        self.assertIn("i.onload = i.onerror = r", vs.PROBE_JS)

    def test_checks_all_five_categories(self):
        for key in ("overflow", "hero_fold", "broken_images",
                    "zero_size_images", "hidden_hero"):
            self.assertIn(key, vs.PROBE_JS)

    def test_returns_json_string(self):
        self.assertIn("JSON.stringify(out)", vs.PROBE_JS)


# --------------------------------------------------------------------------
# check_page — CDP calls mocked
# --------------------------------------------------------------------------

class CheckPageTests(unittest.TestCase):
    def _chrome(self, report=None):
        chrome = mock.Mock()
        payload = json.dumps(report or {"viewport": {"w": 390, "h": 844}, "failures": {}})

        def call(method, params=None, timeout=60):
            if method == "Runtime.evaluate":
                return {"result": {"value": payload}}
            if method == "Page.captureScreenshot":
                return {"data": vs.base64.b64encode(b"PNGDATA").decode()}
            return {}

        chrome.call.side_effect = call
        return chrome

    def test_sets_exact_viewport_not_window_size(self):
        chrome = self._chrome()
        vs.check_page(chrome, "file:///x.html", 390, 844)
        metrics = [c for c in chrome.call.call_args_list
                   if c[0][0] == "Emulation.setDeviceMetricsOverride"]
        self.assertEqual(len(metrics), 1)
        params = metrics[0][0][1]
        self.assertEqual(params["width"], 390)
        self.assertEqual(params["height"], 844)
        self.assertTrue(params["mobile"], "narrow viewports should emulate mobile")

    def test_desktop_viewport_is_not_mobile(self):
        chrome = self._chrome()
        vs.check_page(chrome, "file:///x.html", 1440, 900)
        params = [c[0][1] for c in chrome.call.call_args_list
                  if c[0][0] == "Emulation.setDeviceMetricsOverride"][0]
        self.assertFalse(params["mobile"])

    def test_navigates_to_the_url(self):
        chrome = self._chrome()
        vs.check_page(chrome, "file:///tmp/index.html", 390, 844)
        nav = [c[0][1] for c in chrome.call.call_args_list if c[0][0] == "Page.navigate"]
        self.assertEqual(nav[0]["url"], "file:///tmp/index.html")

    def test_awaits_the_probe_promise(self):
        chrome = self._chrome()
        vs.check_page(chrome, "file:///x.html", 390, 844)
        ev = [c for c in chrome.call.call_args_list if c[0][0] == "Runtime.evaluate"][0]
        self.assertTrue(ev[0][1]["awaitPromise"])
        self.assertTrue(ev[0][1]["returnByValue"])

    def test_returns_parsed_report(self):
        want = {"viewport": {"w": 390, "h": 844}, "failures": {"overflow": {"elements": []}}}
        got = vs.check_page(self._chrome(want), "file:///x.html", 390, 844)
        self.assertEqual(got, want)

    def test_writes_screenshot_when_requested(self):
        chrome = self._chrome()
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "shot.png")
            vs.check_page(chrome, "file:///x.html", 390, 844, shot_path=out)
            with open(out, "rb") as f:
                self.assertEqual(f.read(), b"PNGDATA")

    def test_no_screenshot_call_when_not_requested(self):
        chrome = self._chrome()
        vs.check_page(chrome, "file:///x.html", 390, 844)
        self.assertNotIn("Page.captureScreenshot",
                         [c[0][0] for c in chrome.call.call_args_list])

    def test_raises_when_probe_returns_nothing(self):
        chrome = mock.Mock()
        chrome.call.return_value = {"result": {}}
        with self.assertRaises(RuntimeError):
            vs.check_page(chrome, "file:///x.html", 390, 844)


# --------------------------------------------------------------------------
# main — exit codes
# --------------------------------------------------------------------------

class MainTests(unittest.TestCase):
    def test_missing_page_exits_3(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(vs.main(["--dir", d]), 3)

    def test_bad_viewport_exits_3(self):
        d = make_project()
        try:
            self.assertEqual(vs.main(["--dir", d, "--viewport", "nope"]), 3)
        finally:
            __import__("shutil").rmtree(d)

    def test_missing_chrome_exits_4(self):
        d = make_project()
        try:
            with mock.patch.object(vs, "find_chrome", return_value=None):
                self.assertEqual(vs.main(["--dir", d]), 4)
        finally:
            __import__("shutil").rmtree(d)

    def test_chrome_launch_failure_exits_4(self):
        d = make_project()
        try:
            with mock.patch.object(vs, "find_chrome", return_value="/bin/chrome"), \
                 mock.patch.object(vs, "Chrome", side_effect=RuntimeError("boom")):
                self.assertEqual(vs.main(["--dir", d]), 4)
        finally:
            __import__("shutil").rmtree(d)

    def _run(self, argv, failures):
        d = make_project()
        chrome = mock.Mock()
        report = {"viewport": {"w": 390, "h": 844}, "failures": failures}
        try:
            with mock.patch.object(vs, "find_chrome", return_value="/bin/chrome"), \
                 mock.patch.object(vs, "Chrome", return_value=chrome), \
                 mock.patch.object(vs, "check_page", return_value=report):
                return vs.main(["--dir", d] + argv), chrome
        finally:
            __import__("shutil").rmtree(d)

    def test_clean_site_exits_0(self):
        rc, chrome = self._run(["--viewport", "390x844"], {})
        self.assertEqual(rc, 0)
        chrome.close.assert_called_once()

    def test_failing_site_exits_1(self):
        rc, _ = self._run(["--viewport", "390x844"], {"overflow": {"elements": []}})
        self.assertEqual(rc, 1)

    def test_chrome_is_closed_even_on_error(self):
        d = make_project()
        chrome = mock.Mock()
        try:
            with mock.patch.object(vs, "find_chrome", return_value="/bin/chrome"), \
                 mock.patch.object(vs, "Chrome", return_value=chrome), \
                 mock.patch.object(vs, "check_page", side_effect=RuntimeError("nav failed")):
                self.assertEqual(vs.main(["--dir", d]), 4)
            chrome.close.assert_called_once()
        finally:
            __import__("shutil").rmtree(d)

    def test_checks_every_default_viewport(self):
        d = make_project()
        seen = []
        try:
            with mock.patch.object(vs, "find_chrome", return_value="/bin/chrome"), \
                 mock.patch.object(vs, "Chrome", return_value=mock.Mock()), \
                 mock.patch.object(vs, "check_page",
                                   side_effect=lambda c, u, w, h, shot_path=None: (
                                       seen.append((w, h)) or
                                       {"viewport": {"w": w, "h": h}, "failures": {}})):
                self.assertEqual(vs.main(["--dir", d]), 0)
            self.assertEqual(seen, [vs.parse_viewport(v) for v in vs.DEFAULT_VIEWPORTS])
            self.assertIn((390, 844), seen, "the true-mobile width must be covered")
        finally:
            __import__("shutil").rmtree(d)

    def test_json_output_is_valid(self):
        d = make_project()
        buf = []
        try:
            with mock.patch.object(vs, "find_chrome", return_value="/bin/chrome"), \
                 mock.patch.object(vs, "Chrome", return_value=mock.Mock()), \
                 mock.patch.object(vs, "check_page",
                                   return_value={"viewport": {"w": 390, "h": 844},
                                                 "failures": {}}), \
                 mock.patch("builtins.print", side_effect=lambda *a, **k: buf.append(a)):
                vs.main(["--dir", d, "--viewport", "390x844", "--json"])
            payload = json.loads(buf[0][0])
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["page"], "index.html")
        finally:
            __import__("shutil").rmtree(d)

    def test_alternate_page_is_honoured(self):
        d = make_project()
        with open(os.path.join(d, "public", "contact.html"), "w") as f:
            f.write("<html></html>")
        urls = []
        try:
            with mock.patch.object(vs, "find_chrome", return_value="/bin/chrome"), \
                 mock.patch.object(vs, "Chrome", return_value=mock.Mock()), \
                 mock.patch.object(vs, "check_page",
                                   side_effect=lambda c, u, w, h, shot_path=None: (
                                       urls.append(u) or
                                       {"viewport": {"w": w, "h": h}, "failures": {}})):
                vs.main(["--dir", d, "--page", "contact.html", "--viewport", "390x844"])
            self.assertTrue(urls[0].endswith("/public/contact.html"))
            self.assertTrue(urls[0].startswith("file://"))
        finally:
            __import__("shutil").rmtree(d)


if __name__ == "__main__":
    unittest.main()

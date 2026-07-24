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


class StaticCheckTests(unittest.TestCase):
    def _css(self, body):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "styles.css"), "w") as f:
            f.write(body)
        return d

    def test_no_css_file_is_not_a_failure(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(vs.static_checks(d), {})

    def test_clean_css_passes(self):
        d = self._css("*{min-width:0}\nhtml{scroll-padding-top:4rem}\n.nav{position:sticky}")
        self.assertEqual(vs.static_checks(d), {})

    def test_flags_sticky_without_scroll_padding(self):
        d = self._css("*{min-width:0}\n.nav{position:sticky;top:0}")
        self.assertIn("missing_scroll_padding", vs.static_checks(d))

    def test_flags_body_overflow_x_hidden(self):
        d = self._css("*{min-width:0}\nbody{margin:0;overflow-x:hidden}")
        self.assertIn("overflow_x_hidden", vs.static_checks(d))

    def test_flags_missing_min_width_reset(self):
        d = self._css("body{margin:0}")
        self.assertIn("no_min_width_reset", vs.static_checks(d))

    def test_comments_are_stripped_before_matching(self):
        """Regression: a comment explaining that a property was deliberately
        omitted must not read as the property being present."""
        d = self._css(
            "*{min-width:0}\nhtml{scroll-padding-top:4rem}\n"
            "body{margin:0; /* NOTE: no overflow-x: hidden here on purpose */}")
        self.assertNotIn("overflow_x_hidden", vs.static_checks(d))


class SummarizeStaticTests(unittest.TestCase):
    def test_static_failures_count_toward_the_verdict(self):
        reports = [{"viewport": {"w": 390, "h": 844}, "failures": {}}]
        self.assertEqual(vs.summarize(reports, {}), (True, 0))
        ok, n = vs.summarize(reports, {"overflow_x_hidden": "..."})
        self.assertFalse(ok)
        self.assertEqual(n, 1)


class SubmitProbeTests(unittest.TestCase):
    """Contract guards on the submit probe."""

    def test_never_posts_to_a_real_form_backend(self):
        self.assertIn("formbackend", vs.FETCH_STUB)
        self.assertIn("web3forms", vs.FETCH_STUB)
        self.assertIn("__verifySubmitted", vs.FETCH_STUB)

    def test_waits_for_load_before_submitting(self):
        """Submitting before the deferred handler attaches causes a native POST
        that navigates away and kills the execution context."""
        self.assertIn("readyState !== 'complete'", vs.SUBMIT_JS)

    def test_scrolls_to_the_button_first(self):
        """Testing from scroll 0 hides the whole bug class."""
        self.assertIn("scrollIntoView({ block: 'end' })", vs.SUBMIT_JS)

    def test_fails_on_document_height_change(self):
        self.assertIn("document_collapse", vs.SUBMIT_JS)
        self.assertIn("Math.abs(heightDelta) > 100", vs.SUBMIT_JS)

    def test_checks_confirmation_visibility_and_header(self):
        self.assertIn("confirmation_offscreen", vs.SUBMIT_JS)
        self.assertIn("confirmation_under_header", vs.SUBMIT_JS)

    def test_overflow_scan_is_ungated(self):
        """The element scan must not sit behind `if (scrollWidth > vw)` — that
        misses everything when body clips overflow."""
        self.assertIn("if (wide.length || de.scrollWidth > vw + TOL)", vs.PROBE_JS)

    def test_scoped_clipping_counts_but_body_does_not(self):
        self.assertIn("p !== document.body", vs.PROBE_JS)
        self.assertIn("!contained(e)", vs.PROBE_JS)


class CheckFormSubmitTests(unittest.TestCase):
    def _chrome(self, payload):
        chrome = mock.Mock()

        def call(method, params=None, timeout=60):
            if method == "Runtime.evaluate":
                return {"result": {"value": json.dumps(payload)}}
            return {}

        chrome.call.side_effect = call
        return chrome

    def test_installs_the_fetch_stub_before_navigating(self):
        chrome = self._chrome({"failures": {}})
        vs.check_form_submit(chrome, "file:///x.html", 390, 844)
        methods = [c[0][0] for c in chrome.call.call_args_list]
        self.assertIn("Page.addScriptToEvaluateOnNewDocument", methods)
        self.assertLess(methods.index("Page.addScriptToEvaluateOnNewDocument"),
                        methods.index("Page.navigate"),
                        "the stub must be installed before the page loads")

    def test_returns_none_when_page_has_no_form(self):
        chrome = self._chrome({"skipped": "no form on this page"})
        self.assertIsNone(vs.check_form_submit(chrome, "file:///x.html", 390, 844))

    def test_navigation_error_becomes_a_reported_failure(self):
        chrome = mock.Mock()

        def call(method, params=None, timeout=60):
            if method == "Runtime.evaluate":
                raise RuntimeError("Runtime.evaluate: Inspected target navigated or closed")
            return {}

        chrome.call.side_effect = call
        report = vs.check_form_submit(chrome, "file:///x.html", 390, 844)
        self.assertIn("native_navigation", report["failures"])

    def test_other_errors_still_raise(self):
        chrome = mock.Mock()

        def call(method, params=None, timeout=60):
            if method == "Runtime.evaluate":
                raise RuntimeError("something else entirely")
            return {}

        chrome.call.side_effect = call
        with self.assertRaises(RuntimeError):
            vs.check_form_submit(chrome, "file:///x.html", 390, 844)


class ProbeSourceTests(unittest.TestCase):
    """The probe is a string, so guard its contract here."""

    def test_awaits_fonts_and_images_before_measuring(self):
        self.assertIn("document.fonts.ready", vs.PROBE_JS)
        self.assertIn("i.onload = i.onerror = r", vs.PROBE_JS)

    def test_every_wait_is_bounded(self):
        """Regression: loading="lazy" images never fire load/error, so an
        unbounded Promise.all on them hangs the probe forever."""
        self.assertIn("Promise.race", vs.PROBE_JS)
        self.assertIn("bounded(document.fonts.ready", vs.PROBE_JS)
        self.assertIn("bounded(Promise.all(", vs.PROBE_JS)

    def test_checks_all_five_categories(self):
        for key in ("overflow", "hero_fold", "broken_images",
                    "zero_size_images", "hidden_hero"):
            self.assertIn(key, vs.PROBE_JS)

    def test_returns_json_string(self):
        self.assertIn("JSON.stringify(out)", vs.PROBE_JS)

    def test_hidden_hero_tests_duration_not_the_value(self):
        """Regression: /transition/.test(c.transitionProperty) never matches —
        the computed value reads e.g. "opacity" — which silently disabled the
        check. Must test for a non-zero duration / named animation instead."""
        self.assertIn("parseFloat(c.transitionDuration) > 0", vs.PROBE_JS)
        self.assertIn("c.animationName !== 'none'", vs.PROBE_JS)
        self.assertNotIn("/transition|animation/.test", vs.PROBE_JS)

    def test_image_gap_ignores_the_css_initial_fill(self):
        """object-fit:fill is the initial value; matching it would flag every
        unstyled image on the page."""
        self.assertIn("fit !== 'cover' && fit !== 'contain'", vs.PROBE_JS)


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
                 mock.patch.object(vs, "check_page", return_value=report), \
                 mock.patch.object(vs, "check_form_submit", return_value=None), \
                 mock.patch.object(vs, "static_checks", return_value={}):
                return vs.main(["--dir", d] + argv), chrome
        finally:
            __import__("shutil").rmtree(d)

    def test_form_check_runs_by_default_and_can_be_skipped(self):
        d = make_project()
        try:
            for argv, want in ([], True), (["--no-form"], False):
                with mock.patch.object(vs, "find_chrome", return_value="/bin/chrome"), \
                     mock.patch.object(vs, "Chrome", return_value=mock.Mock()), \
                     mock.patch.object(vs, "check_page",
                                       return_value={"viewport": {"w": 390, "h": 844},
                                                     "failures": {}}), \
                     mock.patch.object(vs, "static_checks", return_value={}), \
                     mock.patch.object(vs, "check_form_submit",
                                       return_value=None) as form:
                    vs.main(["--dir", d, "--viewport", "390x844"] + argv)
                self.assertEqual(form.called, want)
        finally:
            __import__("shutil").rmtree(d)

    def test_form_failure_fails_the_build(self):
        d = make_project()
        try:
            with mock.patch.object(vs, "find_chrome", return_value="/bin/chrome"), \
                 mock.patch.object(vs, "Chrome", return_value=mock.Mock()), \
                 mock.patch.object(vs, "check_page",
                                   return_value={"viewport": {"w": 390, "h": 844},
                                                 "failures": {}}), \
                 mock.patch.object(vs, "static_checks", return_value={}), \
                 mock.patch.object(vs, "check_form_submit",
                                   return_value={"viewport": {"w": 390, "h": 844},
                                                 "failures": {"document_collapse": {}}}):
                self.assertEqual(vs.main(["--dir", d, "--viewport", "390x844"]), 1)
        finally:
            __import__("shutil").rmtree(d)

    def test_static_failure_alone_fails_the_build(self):
        d = make_project()
        try:
            with mock.patch.object(vs, "find_chrome", return_value="/bin/chrome"), \
                 mock.patch.object(vs, "Chrome", return_value=mock.Mock()), \
                 mock.patch.object(vs, "check_page",
                                   return_value={"viewport": {"w": 390, "h": 844},
                                                 "failures": {}}), \
                 mock.patch.object(vs, "check_form_submit", return_value=None), \
                 mock.patch.object(vs, "static_checks",
                                   return_value={"overflow_x_hidden": "..."}):
                self.assertEqual(vs.main(["--dir", d, "--viewport", "390x844"]), 1)
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
                 mock.patch.object(vs, "check_form_submit", return_value=None), \
                 mock.patch.object(vs, "static_checks", return_value={}), \
                 mock.patch.object(vs, "check_page",
                                   side_effect=lambda c, u, w, h, shot_path=None, **kw: (
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
                 mock.patch.object(vs, "check_form_submit", return_value=None), \
                 mock.patch.object(vs, "static_checks", return_value={}), \
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
                 mock.patch.object(vs, "check_form_submit", return_value=None), \
                 mock.patch.object(vs, "static_checks", return_value={}), \
                 mock.patch.object(vs, "check_page",
                                   side_effect=lambda c, u, w, h, shot_path=None, **kw: (
                                       urls.append(u) or
                                       {"viewport": {"w": w, "h": h}, "failures": {}})):
                vs.main(["--dir", d, "--page", "contact.html", "--viewport", "390x844"])
            self.assertTrue(urls[0].endswith("/public/contact.html"))
            self.assertTrue(urls[0].startswith("file://"))
        finally:
            __import__("shutil").rmtree(d)


# --------------------------------------------------------------------------
# filmstrip — screen-by-screen capture
# --------------------------------------------------------------------------

class FilmstripPrepSourceTests(unittest.TestCase):
    """The prep is a JS string. If it regresses the frames silently lie:
    below-the-fold sections photograph blank and bugs get chased that
    aren't there."""

    def test_freezes_animation_so_runs_are_reproducible(self):
        self.assertIn("animation-play-state:paused", vs.FILMSTRIP_PREP_JS)
        self.assertIn("transition:none", vs.FILMSTRIP_PREP_JS)

    def test_eager_loads_lazy_images(self):
        self.assertIn("img.loading = 'eager'", vs.FILMSTRIP_PREP_JS)

    def test_unhides_reveal_elements_by_behaviour_not_class_name(self):
        """Class names differ per build, so detection must be behavioural."""
        self.assertIn("transitionDuration", vs.FILMSTRIP_PREP_JS)
        self.assertIn("animationName", vs.FILMSTRIP_PREP_JS)
        self.assertIn("parseFloat(c.opacity) < 0.05", vs.FILMSTRIP_PREP_JS)
        self.assertIn("'opacity', '1', 'important'", vs.FILMSTRIP_PREP_JS)
        self.assertNotIn(".reveal", vs.FILMSTRIP_PREP_JS)

    def test_round_trips_the_scroll_to_trigger_observers(self):
        self.assertIn("window.scrollTo(0, H())", vs.FILMSTRIP_PREP_JS)
        self.assertIn("window.scrollTo(0, 0)", vs.FILMSTRIP_PREP_JS)

    def test_image_wait_is_bounded(self):
        """Regression: a lazy image that never fires load/error would hang."""
        self.assertIn("setTimeout(r, 3000)", vs.FILMSTRIP_PREP_JS)

    def test_returns_measured_height(self):
        self.assertIn("height: H()", vs.FILMSTRIP_PREP_JS)

    def test_ends_at_top_of_page(self):
        """Frame 01 must be the top of the page, not wherever prep left off."""
        tail = vs.FILMSTRIP_PREP_JS.rstrip()[-260:]
        self.assertIn("window.scrollTo(0, 0)", tail)


class CaptureFilmstripTests(unittest.TestCase):
    def _chrome(self, height=2000):
        chrome = mock.Mock()
        scrolls = []

        def call(method, params=None, timeout=60):
            if method == "Runtime.evaluate":
                expr = (params or {}).get("expression", "")
                # the capture loop's scroll is exactly "window.scrollTo(0,N); 0";
                # the prep script also contains scrollTo, so match on the prefix
                if expr.startswith("window.scrollTo(0,"):
                    scrolls.append(expr)
                    return {"result": {"value": 0}}
                return {"result": {"value": json.dumps(
                    {"height": height, "viewportH": 844})}}
            if method == "Page.captureScreenshot":
                return {"data": vs.base64.b64encode(b"PNG").decode()}
            return {}

        chrome.call.side_effect = call
        chrome.scrolls = scrolls
        return chrome

    def test_frame_count_covers_whole_page(self):
        chrome = self._chrome(height=10855)
        with tempfile.TemporaryDirectory() as d:
            out = vs.capture_filmstrip(chrome, d, "index", 390, 844)
        # ceil(10855/844) == 13
        self.assertEqual(len(out["frames"]), 13)
        self.assertEqual(out["page_height"], 10855)
        self.assertEqual(out["viewport"], "390x844")

    def test_one_frame_for_a_single_screen_page(self):
        chrome = self._chrome(height=600)
        with tempfile.TemporaryDirectory() as d:
            out = vs.capture_filmstrip(chrome, d, "index", 390, 844)
        self.assertEqual(len(out["frames"]), 1)

    def test_scrolls_one_viewport_at_a_time(self):
        chrome = self._chrome(height=2532)   # exactly 3 screens at 844
        with tempfile.TemporaryDirectory() as d:
            vs.capture_filmstrip(chrome, d, "index", 390, 844)
        offsets = [int(s.split("scrollTo(0,")[1].split(")")[0])
                   for s in chrome.scrolls]
        self.assertEqual(offsets, [0, 844, 1688])

    def test_last_offset_is_clamped_to_max_scroll(self):
        """A page that isn't a whole multiple must not scroll past the bottom."""
        chrome = self._chrome(height=1000)
        with tempfile.TemporaryDirectory() as d:
            vs.capture_filmstrip(chrome, d, "index", 390, 844)
        offsets = [int(s.split("scrollTo(0,")[1].split(")")[0])
                   for s in chrome.scrolls]
        self.assertEqual(offsets, [0, 156])          # 1000 - 844
        self.assertLessEqual(max(offsets), 1000 - 844)

    def test_writes_one_png_per_screen_with_sortable_names(self):
        chrome = self._chrome(height=2532)
        with tempfile.TemporaryDirectory() as d:
            out = vs.capture_filmstrip(chrome, d, "index", 390, 844)
            self.assertEqual(sorted(os.listdir(d)),
                             ["index-390x844-01.png",
                              "index-390x844-02.png",
                              "index-390x844-03.png"])
            for p in out["frames"]:
                with open(p, "rb") as f:
                    self.assertEqual(f.read(), b"PNG")

    def test_deletes_stale_frames_for_same_page_and_viewport(self):
        """A previously longer page must not leave orphan frames behind."""
        with tempfile.TemporaryDirectory() as d:
            for i in range(1, 10):
                open(os.path.join(d, f"index-390x844-{i:02d}.png"), "w").close()
            # 500px page at an 844px viewport is a single screen
            vs.capture_filmstrip(self._chrome(height=500), d, "index", 390, 844)
            self.assertEqual(sorted(os.listdir(d)), ["index-390x844-01.png"])

    def test_leaves_other_pages_and_viewports_alone(self):
        with tempfile.TemporaryDirectory() as d:
            keep = [os.path.join(d, "contact-390x844-01.png"),
                    os.path.join(d, "index-1440x900-01.png")]
            for p in keep:
                open(p, "w").close()
            vs.capture_filmstrip(self._chrome(height=900), d, "index", 390, 844)
            for p in keep:
                self.assertTrue(os.path.exists(p), f"{p} should not be deleted")

    def test_awaits_the_prep_promise(self):
        chrome = self._chrome()
        with tempfile.TemporaryDirectory() as d:
            vs.capture_filmstrip(chrome, d, "index", 390, 844)
        prep = [c[0][1] for c in chrome.call.call_args_list
                if c[0][0] == "Runtime.evaluate"][0]
        self.assertTrue(prep["awaitPromise"])
        self.assertTrue(prep["returnByValue"])

    def test_survives_prep_returning_nothing(self):
        """Never crash the build over a filmstrip — fall back to one screen."""
        chrome = mock.Mock()

        def call(method, params=None, timeout=60):
            if method == "Runtime.evaluate":
                return {"result": {}}
            if method == "Page.captureScreenshot":
                return {"data": vs.base64.b64encode(b"PNG").decode()}
            return {}

        chrome.call.side_effect = call
        with tempfile.TemporaryDirectory() as d:
            out = vs.capture_filmstrip(chrome, d, "index", 390, 844)
        self.assertEqual(len(out["frames"]), 1)
        self.assertEqual(out["page_height"], 844)

    def test_page_shorter_than_viewport_still_yields_one_frame(self):
        chrome = self._chrome(height=100)
        with tempfile.TemporaryDirectory() as d:
            out = vs.capture_filmstrip(chrome, d, "index", 390, 844)
        self.assertEqual(len(out["frames"]), 1)


class CheckPageFilmstripTests(unittest.TestCase):
    def _chrome(self):
        chrome = mock.Mock()
        report = json.dumps({"viewport": {"w": 390, "h": 844}, "failures": {}})
        prep = json.dumps({"height": 1600, "viewportH": 844})
        seen = {"probe": False}

        def call(method, params=None, timeout=60):
            if method == "Runtime.evaluate":
                expr = (params or {}).get("expression", "")
                if expr.startswith("window.scrollTo(0,"):
                    return {"result": {"value": 0}}
                if not seen["probe"]:
                    seen["probe"] = True
                    return {"result": {"value": report}}
                return {"result": {"value": prep}}
            if method == "Page.captureScreenshot":
                return {"data": vs.base64.b64encode(b"PNG").decode()}
            return {}

        chrome.call.side_effect = call
        return chrome

    def test_no_filmstrip_when_dir_not_given(self):
        got = vs.check_page(self._chrome(), "file:///x.html", 390, 844)
        self.assertNotIn("filmstrip", got)

    def test_filmstrip_attached_to_report(self):
        with tempfile.TemporaryDirectory() as d:
            got = vs.check_page(self._chrome(), "file:///x.html", 390, 844,
                                filmstrip_dir=d, page_name="index")
        self.assertEqual(len(got["filmstrip"]["frames"]), 2)   # ceil(1600/844)

    def test_capture_runs_after_the_probe(self):
        """Prep mutates the DOM, so measuring must already be done."""
        order = []
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(vs, "capture_filmstrip",
                                   side_effect=lambda *a, **k: order.append("strip") or {}):
                chrome = self._chrome()
                orig = chrome.call.side_effect

                def spy(method, params=None, timeout=60):
                    if method == "Runtime.evaluate" and not order:
                        order.append("probe")
                    return orig(method, params, timeout)

                chrome.call.side_effect = spy
                vs.check_page(chrome, "file:///x.html", 390, 844,
                              filmstrip_dir=d, page_name="index")
        self.assertEqual(order, ["probe", "strip"])


class MainFilmstripTests(unittest.TestCase):
    def _run(self, extra_argv):
        d = make_project()
        captured = {}
        try:
            with mock.patch.object(vs, "find_chrome", return_value="/bin/chrome"), \
                 mock.patch.object(vs, "Chrome", return_value=mock.Mock()), \
                 mock.patch.object(vs, "check_form_submit", return_value=None), \
                 mock.patch.object(vs, "static_checks", return_value={}), \
                 mock.patch.object(
                     vs, "check_page",
                     side_effect=lambda c, u, w, h, shot_path=None, **kw: (
                         captured.update(kw) or
                         {"viewport": {"w": w, "h": h}, "failures": {}})):
                rc = vs.main(["--dir", d, "--viewport", "390x844"] + extra_argv)
            return rc, captured, d
        finally:
            __import__("shutil").rmtree(d, ignore_errors=True)

    def test_filmstrip_is_on_by_default(self):
        rc, kw, d = self._run([])
        self.assertEqual(rc, 0)
        self.assertTrue(kw["filmstrip_dir"].endswith(".verify"))
        self.assertEqual(kw["page_name"], "index")

    def test_no_filmstrip_flag_disables_it(self):
        rc, kw, _ = self._run(["--no-filmstrip"])
        self.assertEqual(rc, 0)
        self.assertIsNone(kw["filmstrip_dir"])

    def test_filmstrip_dir_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as out:
            rc, kw, _ = self._run(["--filmstrip-dir", out])
            self.assertEqual(rc, 0)
            self.assertEqual(kw["filmstrip_dir"], out)

    def test_default_dir_is_created(self):
        d = make_project()
        try:
            with mock.patch.object(vs, "find_chrome", return_value="/bin/chrome"), \
                 mock.patch.object(vs, "Chrome", return_value=mock.Mock()), \
                 mock.patch.object(vs, "check_form_submit", return_value=None), \
                 mock.patch.object(vs, "static_checks", return_value={}), \
                 mock.patch.object(
                     vs, "check_page",
                     side_effect=lambda c, u, w, h, shot_path=None, **kw:
                         {"viewport": {"w": w, "h": h}, "failures": {}}):
                vs.main(["--dir", d, "--viewport", "390x844"])
            self.assertTrue(os.path.isdir(os.path.join(d, ".verify")))
        finally:
            __import__("shutil").rmtree(d, ignore_errors=True)

    def test_page_name_strips_html_extension(self):
        d = make_project(page="contact.html")
        captured = {}
        try:
            with mock.patch.object(vs, "find_chrome", return_value="/bin/chrome"), \
                 mock.patch.object(vs, "Chrome", return_value=mock.Mock()), \
                 mock.patch.object(vs, "check_form_submit", return_value=None), \
                 mock.patch.object(vs, "static_checks", return_value={}), \
                 mock.patch.object(
                     vs, "check_page",
                     side_effect=lambda c, u, w, h, shot_path=None, **kw: (
                         captured.update(kw) or
                         {"viewport": {"w": w, "h": h}, "failures": {}})):
                vs.main(["--dir", d, "--page", "contact.html",
                         "--viewport", "390x844"])
            self.assertEqual(captured["page_name"], "contact")
        finally:
            __import__("shutil").rmtree(d, ignore_errors=True)

    def test_unwritable_filmstrip_dir_does_not_fail_the_build(self):
        d = make_project()
        try:
            with mock.patch.object(vs, "find_chrome", return_value="/bin/chrome"), \
                 mock.patch.object(vs, "Chrome", return_value=mock.Mock()), \
                 mock.patch.object(vs, "check_form_submit", return_value=None), \
                 mock.patch.object(vs, "static_checks", return_value={}), \
                 mock.patch.object(vs.os, "makedirs",
                                   side_effect=OSError("read-only fs")), \
                 mock.patch.object(
                     vs, "check_page",
                     side_effect=lambda c, u, w, h, shot_path=None, **kw:
                         {"viewport": {"w": w, "h": h}, "failures": {}}):
                self.assertEqual(vs.main(["--dir", d, "--viewport", "390x844"]), 0)
        finally:
            __import__("shutil").rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

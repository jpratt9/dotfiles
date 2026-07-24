"""Unit tests for scripts/ensure_turnstile.py.

Pure file manipulation — no network, no external services to mock. The one
piece of ambient state is the skill's .env (read for TURNSTILE_SITEKEY), which
is patched in every test that touches it so the suite never depends on the real
(gitignored) file.
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "ensure_turnstile.py")

spec = importlib.util.spec_from_file_location("ensure_turnstile", SCRIPT)
ets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ets)

KEY = "0xTESTSITEKEY123"

PAGE_WITH_FORM = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Contact</title>
<link rel="stylesheet" href="styles.css">
</head>
<body>
  <form id="estimate-form" action="https://example.test/f/abc" method="POST">
    <div class="form-fields">
      <input type="text" name="name" required>
    </div>

    <button class="btn" type="submit">Send it</button>
  </form>
</body>
</html>
"""

PAGE_NO_FORM = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Home</title></head>
<body><p>hello</p></body>
</html>
"""


def run(argv):
    """Invoke main() with argv; return (exit_code, parsed_json_or_None)."""
    buf = io.StringIO()
    code = 0
    with mock.patch.object(sys, "argv", ["prog"] + argv):
        with contextlib.redirect_stdout(buf):
            try:
                ets.main()
            except SystemExit as exc:
                code = exc.code or 0
    out = buf.getvalue().strip()
    payload = None
    if out.startswith("{"):
        with contextlib.suppress(json.JSONDecodeError):
            payload = json.loads(out)
    return code, payload


@contextlib.contextmanager
def site(files):
    """Temp site dir preloaded with {relative_name: contents}."""
    with tempfile.TemporaryDirectory() as d:
        for name, body in files.items():
            p = Path(d) / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
        yield Path(d)


class InjectionTests(unittest.TestCase):
    def test_adds_script_and_widget_to_page_with_form(self):
        with site({"contact.html": PAGE_WITH_FORM}) as d:
            code, res = run(["--dir", str(d), "--sitekey", KEY])
            self.assertEqual(code, 0)
            body = (d / "contact.html").read_text()
            self.assertIn(ets.SCRIPT_SRC, body)
            self.assertIn(f'data-sitekey="{KEY}"', body)
            self.assertIn("cf-turnstile", body)
            self.assertEqual(res["html_files_changed"], {"contact.html": 2})

    def test_widget_lands_inside_the_form(self):
        with site({"contact.html": PAGE_WITH_FORM}) as d:
            run(["--dir", str(d), "--sitekey", KEY])
            from bs4 import BeautifulSoup
            soup = BeautifulSoup((d / "contact.html").read_text(), "html.parser")
            form = soup.find("form")
            self.assertIsNotNone(ets.form_widget(form),
                                 "widget must be a descendant of <form> to be submitted")

    def test_script_goes_in_head(self):
        with site({"contact.html": PAGE_WITH_FORM}) as d:
            run(["--dir", str(d), "--sitekey", KEY])
            from bs4 import BeautifulSoup
            soup = BeautifulSoup((d / "contact.html").read_text(), "html.parser")
            srcs = [s.get("src") for s in soup.find("head").find_all("script")]
            self.assertIn(ets.SCRIPT_SRC, srcs)

    def test_is_idempotent(self):
        with site({"contact.html": PAGE_WITH_FORM}) as d:
            run(["--dir", str(d), "--sitekey", KEY])
            once = (d / "contact.html").read_text()
            code, res = run(["--dir", str(d), "--sitekey", KEY])
            self.assertEqual(code, 0)
            self.assertEqual(res["html_files_changed"], {})
            self.assertEqual((d / "contact.html").read_text(), once,
                             "second run must not change the file")

    def test_page_without_form_is_untouched(self):
        with site({"index.html": PAGE_NO_FORM}) as d:
            run(["--dir", str(d), "--sitekey", KEY])
            self.assertEqual((d / "index.html").read_text(), PAGE_NO_FORM)

    def test_contact_html_gets_script_even_with_no_form(self):
        with site({"contact.html": PAGE_NO_FORM}) as d:
            run(["--dir", str(d), "--sitekey", KEY])
            body = (d / "contact.html").read_text()
            self.assertIn(ets.SCRIPT_SRC, body)
            self.assertNotIn("cf-turnstile", body, "no form means no widget")

    def test_every_form_on_a_page_gets_a_widget(self):
        page = textwrap.dedent("""\
            <html><head><title>t</title></head><body>
              <form id="a"><button type="submit">a</button></form>
              <form id="b"><button type="submit">b</button></form>
              <form id="c"><button type="submit">c</button></form>
            </body></html>
            """)
        with site({"multi.html": page}) as d:
            run(["--dir", str(d), "--sitekey", KEY])
            from bs4 import BeautifulSoup
            soup = BeautifulSoup((d / "multi.html").read_text(), "html.parser")
            forms = soup.find_all("form")
            self.assertEqual(len(forms), 3)
            for form in forms:
                self.assertIsNotNone(ets.form_widget(form), f"form #{form.get('id')} missing widget")

    def test_input_type_submit_is_a_valid_anchor(self):
        page = ('<html><head><title>t</title></head><body>'
                '<form><input type="submit" value="Go"></form></body></html>')
        with site({"p.html": page}) as d:
            run(["--dir", str(d), "--sitekey", KEY])
            self.assertIn("cf-turnstile", (d / "p.html").read_text())

    def test_form_without_submit_control_still_gets_widget(self):
        page = ('<html><head><title>t</title></head><body>'
                '<form><input type="text" name="q"></form></body></html>')
        with site({"p.html": page}) as d:
            run(["--dir", str(d), "--sitekey", KEY])
            from bs4 import BeautifulSoup
            soup = BeautifulSoup((d / "p.html").read_text(), "html.parser")
            self.assertIsNotNone(ets.form_widget(soup.find("form")))

    def test_single_line_html_keeps_widget_inside_the_form(self):
        """Regression: splicing at the line start put the widget at byte 0 --
        i.e. outside the form -- when the whole document was one line."""
        for page in (
            '<html><head><title>t</title></head><body>'
            '<form><input type="text" name="q"></form></body></html>',
            '<html><head><title>t</title></head><body>'
            '<form><input type="text" name="q"><button type="submit">go</button></form>'
            '</body></html>',
        ):
            with site({"p.html": page}) as d:
                run(["--dir", str(d), "--sitekey", KEY])
                out = (d / "p.html").read_text()
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(out, "html.parser")
                self.assertIsNotNone(ets.form_widget(soup.find("form")),
                                     f"widget escaped the form: {out}")
                self.assertTrue(out.startswith("<html>"),
                                "document must not gain markup before <html>")

    def test_theme_flag_is_honoured(self):
        with site({"contact.html": PAGE_WITH_FORM}) as d:
            run(["--dir", str(d), "--sitekey", KEY, "--theme", "light"])
            self.assertIn('data-theme="light"', (d / "contact.html").read_text())

    def test_existing_widget_with_other_sitekey_is_left_alone(self):
        page = PAGE_WITH_FORM.replace(
            '<button class="btn" type="submit">Send it</button>',
            '<div class="cf-turnstile" data-sitekey="0xOTHERKEY"></div>\n'
            '    <button class="btn" type="submit">Send it</button>')
        with site({"contact.html": page}) as d:
            code, res = run(["--dir", str(d), "--sitekey", KEY])
            self.assertEqual(code, 0)
            body = (d / "contact.html").read_text()
            self.assertIn("0xOTHERKEY", body)
            self.assertEqual(body.count("cf-turnstile"), 1, "must not add a second widget")
            self.assertTrue(any("different sitekey" in n for n in res["notes"]))


class FormattingPreservationTests(unittest.TestCase):
    """The whole point of splicing rather than reserializing."""

    def test_untouched_bytes_are_preserved(self):
        with site({"contact.html": PAGE_WITH_FORM}) as d:
            run(["--dir", str(d), "--sitekey", KEY])
            after = (d / "contact.html").read_text()
            # every original line survives verbatim; only new lines are added
            for line in PAGE_WITH_FORM.splitlines():
                self.assertIn(line, after.splitlines(),
                              f"original line was rewritten: {line!r}")

    def test_attribute_order_and_void_tags_not_rewritten(self):
        with site({"contact.html": PAGE_WITH_FORM}) as d:
            run(["--dir", str(d), "--sitekey", KEY])
            after = (d / "contact.html").read_text()
            self.assertIn('<meta charset="utf-8">', after)
            self.assertNotIn('<meta charset="utf-8"/>', after)
            self.assertIn('<link rel="stylesheet" href="styles.css">', after)

    def test_anchor_indentation_is_not_disturbed(self):
        with site({"contact.html": PAGE_WITH_FORM}) as d:
            run(["--dir", str(d), "--sitekey", KEY])
            lines = (d / "contact.html").read_text().splitlines()
            btn = next(l for l in lines if "<button" in l)
            self.assertEqual(btn, '    <button class="btn" type="submit">Send it</button>',
                             "submit button must keep its original indentation")
            div = next(l for l in lines if "<div class=\"cf-turnstile" in l)
            self.assertEqual(len(div) - len(div.lstrip()), 4,
                             "widget must match the anchor's indent, not double it")


class CssTests(unittest.TestCase):
    def test_rule_appended_when_absent(self):
        with site({"contact.html": PAGE_WITH_FORM, "styles.css": "body { margin: 0; }\n"}) as d:
            code, res = run(["--dir", str(d), "--sitekey", KEY])
            self.assertEqual(code, 0)
            self.assertTrue(res["css_rule_added"])
            css = (d / "styles.css").read_text()
            self.assertIn(".turnstile-box", css)
            self.assertTrue(css.startswith("body { margin: 0; }"), "existing CSS preserved")

    def test_rule_not_duplicated(self):
        css = "body { margin: 0; }\n.turnstile-box { margin-bottom: 1.25rem; }\n"
        with site({"contact.html": PAGE_WITH_FORM, "styles.css": css}) as d:
            code, res = run(["--dir", str(d), "--sitekey", KEY])
            self.assertFalse(res["css_rule_added"])
            self.assertEqual((d / "styles.css").read_text(), css)

    def test_selector_only_in_a_comment_does_not_count(self):
        css = "/* todo: add .turnstile-box later */\nbody { margin: 0; }\n"
        with site({"contact.html": PAGE_WITH_FORM, "styles.css": css}) as d:
            _, res = run(["--dir", str(d), "--sitekey", KEY])
            self.assertTrue(res["css_rule_added"],
                            "a mention inside a comment is not a rule")

    def test_selector_inside_media_query_counts(self):
        css = "@media (max-width: 600px) { .turnstile-box { min-height: 65px; } }\n"
        with site({"contact.html": PAGE_WITH_FORM, "styles.css": css}) as d:
            _, res = run(["--dir", str(d), "--sitekey", KEY])
            self.assertFalse(res["css_rule_added"], "nested rules must be found")

    def test_missing_stylesheet_is_noted_not_fatal(self):
        with site({"contact.html": PAGE_WITH_FORM}) as d:
            code, res = run(["--dir", str(d), "--sitekey", KEY])
            self.assertEqual(code, 0)
            self.assertFalse(res["css_rule_added"])
            self.assertTrue(any("stylesheet not found" in n for n in res["notes"]))

    def test_custom_css_path(self):
        with site({"contact.html": PAGE_WITH_FORM, "css/main.css": "body{}\n"}) as d:
            run(["--dir", str(d), "--sitekey", KEY, "--css", str(d / "css" / "main.css")])
            self.assertIn(".turnstile-box", (d / "css" / "main.css").read_text())


class CheckModeTests(unittest.TestCase):
    def test_check_reports_without_writing(self):
        with site({"contact.html": PAGE_WITH_FORM, "styles.css": "body{}\n"}) as d:
            code, res = run(["--dir", str(d), "--sitekey", KEY, "--check"])
            self.assertEqual(code, 5, "missing wiring must exit 5")
            self.assertEqual(res["mode"], "check")
            self.assertEqual((d / "contact.html").read_text(), PAGE_WITH_FORM,
                             "--check must not modify files")
            self.assertEqual((d / "styles.css").read_text(), "body{}\n")

    def test_check_passes_when_already_wired(self):
        with site({"contact.html": PAGE_WITH_FORM, "styles.css": "body{}\n"}) as d:
            run(["--dir", str(d), "--sitekey", KEY])
            code, _ = run(["--dir", str(d), "--sitekey", KEY, "--check"])
            self.assertEqual(code, 0)


class SitekeyResolutionTests(unittest.TestCase):
    def test_reads_sitekey_from_env_file(self):
        with tempfile.TemporaryDirectory() as envdir:
            envfile = Path(envdir) / ".env"
            envfile.write_text("FOO=bar\nTURNSTILE_SITEKEY=0xFROMENV\nBAZ=1\n")
            with mock.patch.object(ets, "ENV_PATH", envfile):
                with site({"contact.html": PAGE_WITH_FORM}) as d:
                    code, res = run(["--dir", str(d)])
                    self.assertEqual(code, 0)
                    self.assertEqual(res["sitekey"], "0xFROMENV")

    def test_flag_overrides_env(self):
        with tempfile.TemporaryDirectory() as envdir:
            envfile = Path(envdir) / ".env"
            envfile.write_text("TURNSTILE_SITEKEY=0xFROMENV\n")
            with mock.patch.object(ets, "ENV_PATH", envfile):
                with site({"contact.html": PAGE_WITH_FORM}) as d:
                    _, res = run(["--dir", str(d), "--sitekey", KEY])
                    self.assertEqual(res["sitekey"], KEY)

    def test_exit_2_when_no_sitekey_anywhere(self):
        with tempfile.TemporaryDirectory() as envdir:
            missing = Path(envdir) / "nope.env"
            with mock.patch.object(ets, "ENV_PATH", missing):
                with site({"contact.html": PAGE_WITH_FORM}) as d:
                    code, _ = run(["--dir", str(d)])
                    self.assertEqual(code, 2, "no sitekey is a warn-and-skip, not a crash")
                    self.assertEqual((d / "contact.html").read_text(), PAGE_WITH_FORM)

    def test_blank_sitekey_in_env_is_treated_as_missing(self):
        with tempfile.TemporaryDirectory() as envdir:
            envfile = Path(envdir) / ".env"
            envfile.write_text("TURNSTILE_SITEKEY=\n")
            with mock.patch.object(ets, "ENV_PATH", envfile):
                with site({"contact.html": PAGE_WITH_FORM}) as d:
                    code, _ = run(["--dir", str(d)])
                    self.assertEqual(code, 2)


class UsageTests(unittest.TestCase):
    def test_exit_3_when_dir_missing(self):
        code, _ = run(["--dir", "/definitely/not/here", "--sitekey", KEY])
        self.assertEqual(code, 3)

    def test_walks_nested_directories(self):
        with site({"pages/deep/contact.html": PAGE_WITH_FORM}) as d:
            run(["--dir", str(d), "--sitekey", KEY])
            self.assertIn("cf-turnstile", (d / "pages" / "deep" / "contact.html").read_text())


if __name__ == "__main__":
    unittest.main()

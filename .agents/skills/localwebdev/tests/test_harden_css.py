"""Unit tests for scripts/harden_css.py. Pure text transform — no external calls."""
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "harden_css.py")

spec = importlib.util.spec_from_file_location("harden_css", SCRIPT)
hc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hc)


def run_on(css):
    """Run main() against a temp stylesheet, return (exit_code, new_contents)."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "styles.css")
        with open(p, "w") as f:
            f.write(css)
        rc = hc.main(["--css", p])
        with open(p) as f:
            return rc, f.read()


class InjectionTests(unittest.TestCase):
    def test_injects_all_four_rules(self):
        rc, out = run_on("body { margin: 0; }")
        self.assertEqual(rc, 0)
        self.assertIn("min-width: 0", out)
        self.assertIn("scroll-padding-top", out)
        self.assertIn("max-width: 100%", out)
        self.assertIn("overflow-wrap: anywhere", out)

    def test_original_css_is_preserved(self):
        rc, out = run_on(".hero { color: red; }")
        self.assertIn(".hero { color: red; }", out)

    def test_is_idempotent(self):
        _, once = run_on("body { margin: 0; }")
        _, twice = run_on(once)
        self.assertEqual(once, twice)
        self.assertEqual(twice.count("min-width: 0"), 1)

    def test_missing_file_exits_2(self):
        self.assertEqual(hc.main(["--css", "/nope/does/not/exist.css"]), 2)

    def test_nav_h_has_a_fallback(self):
        """--nav-h may not be defined; the calc() must not collapse to invalid."""
        _, out = run_on("body{}")
        self.assertIn("var(--nav-h, 72px)", out)


class InsertionPointTests(unittest.TestCase):
    """@charset/@import must stay first — CSS ignores them otherwise."""

    def test_block_goes_after_charset(self):
        _, out = run_on('@charset "utf-8";\nbody { margin: 0; }')
        self.assertLess(out.index("@charset"), out.index("min-width: 0"))

    def test_block_goes_after_imports(self):
        css = '@import url("a.css");\n@import url("b.css");\n.x { color: red; }'
        _, out = run_on(css)
        self.assertLess(out.index('@import url("b.css")'), out.index("min-width: 0"))

    def test_block_precedes_author_rules_so_they_can_override(self):
        _, out = run_on(".card { min-width: 240px; }")
        self.assertLess(out.index("box-sizing: border-box"),
                        out.index(".card { min-width: 240px; }"),
                        "author rules must come after, so they still win")


class OverflowStripTests(unittest.TestCase):
    def test_strips_overflow_x_hidden_from_body(self):
        _, out = run_on("body { margin: 0; overflow-x: hidden; color: red; }")
        self.assertNotIn("overflow-x: hidden", out)
        self.assertIn("color: red", out)
        self.assertIn("margin: 0", out)

    def test_strips_from_grouped_selector(self):
        _, out = run_on("html, body { overflow-x: hidden; margin: 0; }")
        self.assertNotIn("overflow-x: hidden", out)

    def test_strips_unspaced_form(self):
        _, out = run_on("body{overflow-x:hidden;margin:0}")
        self.assertNotIn("overflow-x:hidden", out)
        self.assertIn("margin:0", out)

    def test_strips_when_last_declaration_without_semicolon(self):
        _, out = run_on("body { margin: 0; overflow-x: hidden }")
        self.assertNotIn("overflow-x", out)

    def test_leaves_other_elements_alone(self):
        """Scoped containment on a section is the correct pattern — keep it."""
        _, out = run_on(".hero { overflow-x: clip; }\n"
                        ".marquee { overflow-x: hidden; }\n"
                        "body { margin: 0; }")
        self.assertIn(".hero { overflow-x: clip; }", out)
        self.assertIn(".marquee { overflow-x: hidden; }", out)

    def test_strips_even_when_marker_already_present(self):
        """A second run must still clean a newly-added body overflow-x."""
        _, once = run_on("body { margin: 0; }")
        rc, twice = run_on(once.replace("body { margin: 0; }",
                                        "body { margin: 0; overflow-x: hidden; }"))
        self.assertEqual(rc, 0)
        self.assertNotIn("overflow-x: hidden", twice)


class HardenFnTests(unittest.TestCase):
    def test_reports_already_present(self):
        first, was_present, _ = hc.harden("body{}")
        self.assertFalse(was_present)
        _, already, _ = hc.harden(first)
        self.assertTrue(already)

    def test_reports_removal_count(self):
        _, _, removed = hc.harden("body { overflow-x: hidden; }")
        self.assertEqual(removed, 1)

    def test_no_removal_reported_when_clean(self):
        _, _, removed = hc.harden("body { margin: 0; }")
        self.assertEqual(removed, 0)


class OutputIsValidCssTests(unittest.TestCase):
    def test_braces_stay_balanced(self):
        css = ("@import url('x.css');\n"
               "html, body { margin: 0; overflow-x: hidden; }\n"
               "@media (max-width: 700px) { .a { color: red; } }\n")
        _, out = run_on(css)
        self.assertEqual(out.count("{"), out.count("}"))


if __name__ == "__main__":
    unittest.main()

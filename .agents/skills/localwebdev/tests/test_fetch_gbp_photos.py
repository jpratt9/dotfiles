"""Unit tests for scripts/fetch_gbp_photos.py.

All external calls (Apify actor run, image downloads) are MOCKED — the real
Apify API and googleusercontent are never hit.
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
SCRIPT = os.path.join(HERE, "..", "scripts", "fetch_gbp_photos.py")

spec = importlib.util.spec_from_file_location("fetch_gbp_photos", SCRIPT)
gbp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gbp)


class FakeResp:
    """Minimal context-manager stand-in for an http.client response."""
    def __init__(self, body=b"", content_type="application/json"):
        self._body = body
        self.headers = {"Content-Type": content_type}
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def read(self):
        return self._body


class NormalizeSizeTests(unittest.TestCase):
    def test_rewrites_existing_size_directive(self):
        url = "https://lh3.googleusercontent.com/gps-cs-s/ABC=w86-h114-k-no"
        self.assertEqual(gbp.normalize_size(url, "s1600"),
                         "https://lh3.googleusercontent.com/gps-cs-s/ABC=s1600")

    def test_appends_when_no_directive(self):
        url = "https://lh3.googleusercontent.com/p/ABC"
        self.assertEqual(gbp.normalize_size(url, "s1600"), url + "=s1600")

    def test_leaves_non_google_hosts_alone(self):
        url = "https://example.com/pic.jpg=w100"
        self.assertEqual(gbp.normalize_size(url, "s1600"), url)


class ExtractPhotosTests(unittest.TestCase):
    def test_handles_varied_shapes_and_owner_flag(self):
        items = [{
            "placeName": "Chicken Latino",
            "photos": [
                {"imageUrl": "https://lh3.googleusercontent.com/a", "category": "By owner"},
                {"url": "https://lh3.googleusercontent.com/b", "isOwner": True},
                {"image": "https://lh3.googleusercontent.com/c", "photoCategory": "Food"},
                "https://lh3.googleusercontent.com/d",
            ],
        }]
        photos = gbp.extract_photos(items)
        self.assertEqual(len(photos), 4)
        self.assertEqual([p["owner"] for p in photos], [True, True, False, False])
        self.assertEqual(photos[0]["place"], "Chicken Latino")

    def test_skips_items_without_a_url(self):
        items = [{"photos": [{"width": 100}, {"imageUrl": ""}]}]
        self.assertEqual(gbp.extract_photos(items), [])


class RunActorTests(unittest.TestCase):
    def test_returns_dataset_items_and_builds_url(self):
        payload = [{"placeName": "X", "photos": ["https://lh3.googleusercontent.com/a"]}]
        resp = FakeResp(json.dumps(payload).encode())
        with mock.patch.object(gbp.urllib.request, "urlopen", return_value=resp) as m:
            out = gbp.run_actor("https://maps/place", "tok")
        self.assertEqual(out, payload)
        called_url = m.call_args.args[0].full_url
        self.assertIn("solidcode~google-maps-photos-scraper", called_url)
        self.assertIn("token=tok", called_url)

    def test_error_payload_exits_4(self):
        resp = FakeResp(json.dumps({"error": "nope"}).encode())
        with mock.patch.object(gbp.urllib.request, "urlopen", return_value=resp):
            with self.assertRaises(SystemExit) as cm:
                gbp.run_actor("u", "t")
        self.assertEqual(cm.exception.code, 4)


class DownloadTests(unittest.TestCase):
    def test_writes_image_bytes(self):
        resp = FakeResp(b"\xff\xd8\xff", content_type="image/jpeg")
        with mock.patch.object(gbp.urllib.request, "urlopen", return_value=resp):
            with tempfile.TemporaryDirectory() as d:
                dest = os.path.join(d, "p.jpg")
                gbp.download("https://lh3.googleusercontent.com/a", dest)
                with open(dest, "rb") as f:
                    self.assertEqual(f.read(), b"\xff\xd8\xff")

    def test_rejects_non_image(self):
        resp = FakeResp(b"<html>", content_type="text/html")
        with mock.patch.object(gbp.urllib.request, "urlopen", return_value=resp):
            with self.assertRaises(ValueError):
                gbp.download("https://lh3.googleusercontent.com/a", "/tmp/x.jpg")


class MainIntegrationTests(unittest.TestCase):
    def test_end_to_end_writes_manifest(self):
        actor_payload = [{
            "placeName": "Chicken Latino",
            "photos": [
                {"imageUrl": "https://lh3.googleusercontent.com/a=w86-h114-k-no"},
                {"imageUrl": "https://lh3.googleusercontent.com/b=s0"},
            ],
        }]

        def fake_urlopen(req, timeout=None):
            url = getattr(req, "full_url", req)
            if "api.apify.com" in url:
                return FakeResp(json.dumps(actor_payload).encode())
            return FakeResp(b"\xff\xd8\xff", content_type="image/jpeg")

        with tempfile.TemporaryDirectory() as d:
            argv = ["prog", "--url", "https://maps/place", "--out", d,
                    "--max", "5", "--token", "tok"]
            with mock.patch.object(gbp.urllib.request, "urlopen", side_effect=fake_urlopen), \
                 mock.patch.object(sys, "argv", argv), \
                 mock.patch.object(sys, "stdout", io.StringIO()):
                gbp.main()
            with open(os.path.join(d, "gallery.json")) as f:
                manifest = json.load(f)
            self.assertEqual(len(manifest), 2)
            self.assertTrue(all(m["source"].endswith("=s1600") for m in manifest))
            self.assertTrue(os.path.exists(os.path.join(d, "photo-01.jpg")))

    def test_missing_token_exits_3(self):
        argv = ["prog", "--url", "u", "--out", "/tmp/whatever"]
        with mock.patch.dict(gbp.os.environ, {}, clear=True), \
             mock.patch.object(sys, "argv", argv):
            with self.assertRaises(SystemExit) as cm:
                gbp.main()
        self.assertEqual(cm.exception.code, 3)


if __name__ == "__main__":
    unittest.main()

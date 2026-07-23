"""Unit tests for scripts/fetch_fb_photos.py.

All external calls (Apify actor run, image downloads) are MOCKED — the real
Apify API and Facebook CDN are never hit.
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
SCRIPT = os.path.join(HERE, "..", "scripts", "fetch_fb_photos.py")

spec = importlib.util.spec_from_file_location("fetch_fb_photos", SCRIPT)
fb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fb)


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


# One page's posts as the actor returns them: a single-photo post, an album
# post, a video post (no still), and the trailing page_summary record.
POSTS = [
    {"recordType": "post", "type": "photo", "message": "Fresh install",
     "author": {"name": "Premier Gutters"},
     "image": {"uri": "https://scontent.x.fbcdn.net/single.jpg?oh=1&oe=2",
               "width": 640, "height": 512},
     "album_preview": None},
    {"recordType": "post", "type": "photo", "message": "Before / after",
     "author": {"name": "Premier Gutters"},
     "image": None,
     "album_preview": {"count": 2, "images": [
         {"uri": "https://scontent.x.fbcdn.net/a.jpg?oh=1&oe=2", "width": 590, "height": 443},
         {"uri": "https://scontent.x.fbcdn.net/b.jpg?oh=1&oe=2", "width": 590, "height": 590},
     ]}},
    {"recordType": "post", "type": "video", "message": "Reel",
     "author": {"name": "Premier Gutters"}, "image": None, "album_preview": None,
     "video_thumbnail": {"uri": "https://scontent.x.fbcdn.net/v.jpg", "width": None, "height": None}},
    {"recordType": "page_summary", "profileUrl": "https://facebook.com/premier",
     "postsCollected": 20, "maxPostsPerProfile": 20},
]


class ExtractPhotosTests(unittest.TestCase):
    def test_single_and_album_photos(self):
        photos = fb.extract_photos(POSTS)
        # 1 single + 2 album = 3; the video post and page_summary contribute none.
        self.assertEqual(len(photos), 3)
        self.assertEqual([p["url"].rsplit("/", 1)[-1].split("?")[0] for p in photos],
                         ["single.jpg", "a.jpg", "b.jpg"])
        self.assertEqual(photos[0]["width"], 640)
        self.assertTrue(all(p["place"] == "Premier Gutters" for p in photos))
        self.assertEqual(photos[1]["caption"], "Before / after")

    def test_skips_page_summary_and_video_and_nulls(self):
        items = [
            {"recordType": "page_summary"},
            {"recordType": "post", "image": None, "album_preview": None},
            {"recordType": "post", "image": {"width": 100}},          # no uri
            {"recordType": "post", "album_preview": {"images": [{"uri": ""}]}},
        ]
        self.assertEqual(fb.extract_photos(items), [])


class RunActorTests(unittest.TestCase):
    def test_returns_dataset_items_and_builds_url(self):
        resp = FakeResp(json.dumps(POSTS).encode())
        with mock.patch.object(fb.urllib.request, "urlopen", return_value=resp) as m:
            out = fb.run_actor("https://facebook.com/premier", "tok", 25)
        self.assertEqual(out, POSTS)
        req = m.call_args.args[0]
        self.assertIn(fb.ACTOR, req.full_url)        # actor slug is in the endpoint
        self.assertIn("token=tok", req.full_url)
        body = json.loads(req.data.decode())          # input carries the page url
        self.assertEqual(body["startUrls"], ["https://facebook.com/premier"])
        self.assertEqual(body["maxPostsPerProfile"], 25)

    def test_error_payload_exits_4(self):
        resp = FakeResp(json.dumps({"error": "nope"}).encode())
        with mock.patch.object(fb.urllib.request, "urlopen", return_value=resp):
            with self.assertRaises(SystemExit) as cm:
                fb.run_actor("u", "t", 10)
        self.assertEqual(cm.exception.code, 4)


class DownloadTests(unittest.TestCase):
    def test_writes_image_bytes(self):
        resp = FakeResp(b"\xff\xd8\xff", content_type="image/jpeg")
        with mock.patch.object(fb.urllib.request, "urlopen", return_value=resp):
            with tempfile.TemporaryDirectory() as d:
                dest = os.path.join(d, "p.jpg")
                fb.download("https://scontent.x.fbcdn.net/a.jpg", dest)
                with open(dest, "rb") as f:
                    self.assertEqual(f.read(), b"\xff\xd8\xff")

    def test_rejects_non_image(self):
        resp = FakeResp(b"<html>", content_type="text/html")
        with mock.patch.object(fb.urllib.request, "urlopen", return_value=resp):
            with self.assertRaises(ValueError):
                fb.download("https://scontent.x.fbcdn.net/a.jpg", "/tmp/x.jpg")


class MainIntegrationTests(unittest.TestCase):
    def test_end_to_end_writes_manifest(self):
        def fake_urlopen(req, timeout=None):
            url = getattr(req, "full_url", req)
            if "api.apify.com" in url:
                return FakeResp(json.dumps(POSTS).encode())
            return FakeResp(b"\xff\xd8\xff", content_type="image/jpeg")

        with tempfile.TemporaryDirectory() as d:
            argv = ["prog", "--url", "https://facebook.com/premier", "--out", d,
                    "--max", "5", "--token", "tok"]
            with mock.patch.object(fb.urllib.request, "urlopen", side_effect=fake_urlopen), \
                 mock.patch.object(sys, "argv", argv), \
                 mock.patch.object(sys, "stdout", io.StringIO()):
                fb.main()
            with open(os.path.join(d, "gallery.json")) as f:
                manifest = json.load(f)
            self.assertEqual(len(manifest), 3)                     # single + 2 album
            self.assertTrue(all(m["owner"] is True for m in manifest))  # page's own posts
            self.assertTrue(all(m["place"] == "Premier Gutters" for m in manifest))
            self.assertTrue(manifest[0]["source"].startswith("https://scontent"))
            self.assertTrue(os.path.exists(os.path.join(d, "photo-01.jpg")))

    def test_missing_token_exits_3(self):
        argv = ["prog", "--url", "u", "--out", "/tmp/whatever"]
        with mock.patch.dict(fb.os.environ, {}, clear=True), \
             mock.patch.object(sys, "argv", argv):
            with self.assertRaises(SystemExit) as cm:
                fb.main()
        self.assertEqual(cm.exception.code, 3)


if __name__ == "__main__":
    unittest.main()

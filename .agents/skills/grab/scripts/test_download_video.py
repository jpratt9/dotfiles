#!/usr/bin/env python3
"""Tests for download_video.py"""

import json
import os
import subprocess
import unittest
from unittest.mock import patch, MagicMock

from download_video import detect_platform, download_video


class TestDetectPlatform(unittest.TestCase):
    def test_youtube(self):
        self.assertEqual(detect_platform("https://www.youtube.com/watch?v=abc"), "YouTube")
        self.assertEqual(detect_platform("https://youtu.be/abc"), "YouTube")

    def test_tiktok(self):
        self.assertEqual(detect_platform("https://www.tiktok.com/@user/video/123"), "TikTok")

    def test_instagram(self):
        self.assertEqual(detect_platform("https://www.instagram.com/reel/abc/"), "Instagram")

    def test_facebook(self):
        self.assertEqual(detect_platform("https://www.facebook.com/watch?v=123"), "Facebook")
        self.assertEqual(detect_platform("https://fb.watch/abc"), "Facebook")

    def test_unknown(self):
        self.assertEqual(detect_platform("https://example.com/video"), "Unknown")


class TestDownloadVideo(unittest.TestCase):
    @patch("download_video.subprocess.run")
    def test_metadata_fetch_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="not found")
        result = download_video("https://example.com/bad")
        self.assertIn("error", result)
        self.assertIn("Failed to fetch video info", result["error"])

    @patch("download_video.os.path.exists", return_value=True)
    @patch("download_video.subprocess.run")
    def test_successful_download(self, mock_run, mock_exists):
        metadata = json.dumps({
            "title": "Test Video",
            "duration": 65,
            "ext": "mp4",
        })
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=metadata),  # metadata fetch
            MagicMock(returncode=0),  # download
        ]
        result = download_video("https://www.youtube.com/watch?v=test")
        self.assertEqual(result["title"], "Test Video")
        self.assertEqual(result["platform"], "YouTube")
        self.assertEqual(result["duration"], "1m 5s")
        self.assertIn("Downloads", result["file"])

    @patch("download_video.subprocess.run")
    def test_download_failure(self, mock_run):
        metadata = json.dumps({
            "title": "Fail Video",
            "duration": 10,
            "ext": "mp4",
        })
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=metadata),
            MagicMock(returncode=1, stderr="download error"),
        ]
        result = download_video("https://www.youtube.com/watch?v=fail")
        self.assertIn("error", result)
        self.assertIn("Download failed", result["error"])

    @patch("download_video.subprocess.run")
    def test_always_downloads_to_user_downloads(self, mock_run):
        metadata = json.dumps({
            "title": "Path Test",
            "duration": 30,
            "ext": "mp4",
        })
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=metadata),
            MagicMock(returncode=0),
        ]
        with patch("download_video.os.path.exists", return_value=True):
            result = download_video("https://www.tiktok.com/@user/video/123")
        downloads_dir = os.path.expanduser("~/Downloads")
        self.assertTrue(result["file"].startswith(downloads_dir))

    @patch("download_video.subprocess.run")
    def test_sanitizes_title(self, mock_run):
        metadata = json.dumps({
            "title": "Video: with <bad> chars!",
            "duration": 10,
            "ext": "mp4",
        })
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=metadata),
            MagicMock(returncode=0),
        ]
        with patch("download_video.os.path.exists", return_value=True):
            result = download_video("https://youtube.com/watch?v=x")
        self.assertNotIn("<", result["file"])
        self.assertNotIn(">", result["file"])
        self.assertNotIn(":", result["file"])


if __name__ == "__main__":
    unittest.main()

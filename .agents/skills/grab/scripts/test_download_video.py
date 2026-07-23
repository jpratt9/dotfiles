#!/usr/bin/env python3
"""Tests for download_video.py"""

import json
import os
import subprocess
import unittest
from unittest.mock import patch, MagicMock

from download_video import (
    BACKOFFS_403,
    IMMEDIATE_RETRIES,
    _is_connection_drop,
    detect_platform,
    download_video,
    run_ytdlp,
)


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


class TestPosterInFilename(unittest.TestCase):
    """The account that posted the video is appended to the filename."""

    def _run(self, meta):
        with patch("download_video.subprocess.run") as mock_run, \
             patch("download_video.os.path.exists", return_value=True):
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=json.dumps(meta)),
                MagicMock(returncode=0),
            ]
            return download_video("https://youtu.be/x")

    def test_uploader_is_appended(self):
        result = self._run({"title": "Some Talk", "duration": 10,
                            "uploader": "SynQ with Saad"})
        self.assertTrue(result["file"].endswith("Some Talk - SynQ with Saad.mp4"))

    def test_channel_used_when_uploader_absent(self):
        result = self._run({"title": "Clip", "duration": 5, "channel": "Chan Name"})
        self.assertTrue(result["file"].endswith("Clip - Chan Name.mp4"))

    def test_no_suffix_when_poster_unknown(self):
        result = self._run({"title": "Anon Clip", "duration": 5})
        self.assertTrue(result["file"].endswith("Anon Clip.mp4"))
        self.assertNotIn(" - .mp4", result["file"])

    def test_poster_is_sanitized(self):
        result = self._run({"title": "Vid", "duration": 5,
                            "uploader": "Bad/Name: <chars>"})
        for ch in "/:<>":
            self.assertNotIn(ch, os.path.basename(result["file"]))

    def test_blank_poster_adds_no_separator(self):
        # A name of only punctuation sanitizes down to nothing.
        result = self._run({"title": "Vid", "duration": 5, "uploader": "!!!"})
        self.assertTrue(result["file"].endswith("Vid.mp4"))

    def test_filename_stays_within_the_byte_limit(self):
        result = self._run({"title": "T" * 300, "duration": 5,
                            "uploader": "U" * 300})
        self.assertLessEqual(len(os.path.basename(result["file"]).encode()), 255)


class TestRunYtdlpRetry(unittest.TestCase):
    """Transient failures retry; everything else returns on the first attempt."""

    # The exact stderr yt-dlp emitted in the report that prompted this feature.
    TIKTOK_DROP = (
        "ERROR: [vm.tiktok] ZTANUtmHd: Unable to download webpage: "
        "('Connection aborted.', RemoteDisconnected('Remote end closed "
        "connection without response'))"
    )

    def test_real_tiktok_error_is_detected_as_a_drop(self):
        self.assertTrue(_is_connection_drop(self.TIKTOK_DROP))

    @patch("download_video.subprocess.run")
    def test_connection_drop_retries_immediately_then_succeeds(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr=self.TIKTOK_DROP),
            MagicMock(returncode=1, stderr=self.TIKTOK_DROP),
            MagicMock(returncode=0, stdout="ok"),
        ]
        result = run_ytdlp(["yt-dlp", "x"], timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(mock_run.call_count, 3)

    @patch("download_video.subprocess.run")
    def test_connection_drop_gives_up_after_three_retries(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr=self.TIKTOK_DROP)
        result = run_ytdlp(["yt-dlp", "x"], timeout=10)
        self.assertEqual(result.returncode, 1)
        # one initial attempt + IMMEDIATE_RETRIES, then it fails.
        self.assertEqual(mock_run.call_count, 1 + IMMEDIATE_RETRIES)

    @patch("download_video.subprocess.run")
    def test_non_transient_error_is_not_retried(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="ERROR: Video unavailable")
        result = run_ytdlp(["yt-dlp", "x"], timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(mock_run.call_count, 1)

    @patch("download_video.time.sleep")
    @patch("download_video.subprocess.run")
    def test_403_still_backs_off_then_succeeds(self, mock_run, mock_sleep):
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr="HTTP Error 403: Forbidden"),
            MagicMock(returncode=0, stdout="ok"),
        ]
        result = run_ytdlp(["yt-dlp", "x"], timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(mock_run.call_count, 2)
        mock_sleep.assert_called_once_with(BACKOFFS_403[0])

    @patch("download_video.time.sleep")
    @patch("download_video.subprocess.run")
    def test_403_gives_up_after_its_backoffs(self, mock_run, mock_sleep):
        mock_run.return_value = MagicMock(returncode=1, stderr="403 forbidden")
        result = run_ytdlp(["yt-dlp", "x"], timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(mock_run.call_count, 1 + len(BACKOFFS_403))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Download a video from a URL using yt-dlp."""

import json
import os
import subprocess
import sys


def detect_platform(url: str) -> str:
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "YouTube"
    if "tiktok.com" in url_lower:
        return "TikTok"
    if "instagram.com" in url_lower:
        return "Instagram"
    if "facebook.com" in url_lower or "fb.watch" in url_lower:
        return "Facebook"
    return "Unknown"


def download_video(url: str) -> dict:
    platform = detect_platform(url)

    # Get metadata first
    result = subprocess.run(
        ["yt-dlp", "--dump-json", "--no-download", url],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        return {"error": f"Failed to fetch video info: {result.stderr.strip()}"}

    info = json.loads(result.stdout)
    title = info.get("title", "Unknown")

    # Instagram's title is a generic "Video by <user>"; the real caption lives in
    # the "description" field. Use it (collapsed to a single line) as the title so
    # the clip is named after what it's actually about.
    if platform == "Instagram":
        caption = " ".join((info.get("description") or "").split())
        if caption:
            title = caption

    duration = info.get("duration", 0)
    duration_str = f"{duration // 60}m {duration % 60}s" if duration else "unknown"

    # Sanitize title for filename. Cap the length — IG captions can run hundreds of
    # chars and would otherwise blow past the filesystem's 255-byte name limit — and
    # collapse the underscore runs that emoji/hashtags/punctuation leave behind.
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    while "__" in safe_title:
        safe_title = safe_title.replace("__", "_")
    safe_title = safe_title[:100].strip(" -_")
    if not safe_title:
        safe_title = "video"

    download_dir = os.path.expanduser("~/Downloads")
    # Use .mp4 directly since --merge-output-format mp4 forces the container.
    # Passing the source ext (e.g. .webm) here causes yt-dlp to write Title.webm.mp4
    # because the template's literal extension stays and the merge tacks on .mp4.
    output_path = os.path.join(download_dir, f"{safe_title}.mp4")

    # Download best quality
    result = subprocess.run(
        ["yt-dlp", "-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4",
         "-o", output_path, url],
        capture_output=True, text=True, timeout=600
    )

    if result.returncode != 0:
        return {"error": f"Download failed: {result.stderr.strip()}"}

    # Defensive fallback: if .mp4 isn't where we expected, find what yt-dlp actually wrote.
    if not os.path.exists(output_path):
        candidates = [f for f in os.listdir(download_dir)
                      if f.startswith(safe_title) and not f.endswith(".json")]
        if candidates:
            output_path = os.path.join(download_dir, candidates[0])
        else:
            return {"error": "Download appeared to succeed but output file not found."}

    return {
        "title": title,
        "platform": platform,
        "duration": duration_str,
        "file": output_path,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: download_video.py <url>"}))
        sys.exit(1)

    result = download_video(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False))

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
    # Get metadata first
    result = subprocess.run(
        ["yt-dlp", "--dump-json", "--no-download", url],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        return {"error": f"Failed to fetch video info: {result.stderr.strip()}"}

    info = json.loads(result.stdout)
    title = info.get("title", "Unknown")
    duration = info.get("duration", 0)
    duration_str = f"{duration // 60}m {duration % 60}s" if duration else "unknown"
    ext = info.get("ext", "mp4")
    platform = detect_platform(url)

    # Sanitize title for filename
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title).strip()
    if not safe_title:
        safe_title = "video"

    output_path = os.path.join(os.getcwd(), f"{safe_title}.{ext}")

    # Download best quality
    result = subprocess.run(
        ["yt-dlp", "-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4",
         "-o", output_path, url],
        capture_output=True, text=True, timeout=600
    )

    if result.returncode != 0:
        return {"error": f"Download failed: {result.stderr.strip()}"}

    # yt-dlp may change the extension to mp4 due to merge
    if not os.path.exists(output_path):
        mp4_path = os.path.splitext(output_path)[0] + ".mp4"
        if os.path.exists(mp4_path):
            output_path = mp4_path
        else:
            # Find whatever file yt-dlp actually wrote
            candidates = [f for f in os.listdir(os.getcwd())
                          if f.startswith(safe_title) and not f.endswith(".json")]
            if candidates:
                output_path = os.path.join(os.getcwd(), candidates[0])
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

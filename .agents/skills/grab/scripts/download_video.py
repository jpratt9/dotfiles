#!/usr/bin/env python3
"""Download a video from a URL using yt-dlp."""

import json
import os
import subprocess
import sys
import time

# YouTube throws transient 403s under load. Back off these many seconds between
# retries -- four attempts total (initial + one per backoff) -- then give up.
BACKOFFS_403 = (3, 6, 9)

# A connection dropped mid-fetch (TikTok's "RemoteDisconnected" especially)
# almost always succeeds on an immediate re-run, so retry these with no backoff.
IMMEDIATE_RETRIES = 3
CONNECTION_DROP_SIGNS = (
    "connection aborted",
    "remotedisconnected",
    "remote end closed connection",
    "connection reset",
    "read timed out",
)


def _is_403(stderr: str) -> bool:
    low = (stderr or "").lower()
    return "403" in low or "forbidden" in low


def _is_connection_drop(stderr: str) -> bool:
    low = (stderr or "").lower()
    return any(sign in low for sign in CONNECTION_DROP_SIGNS)


def run_ytdlp(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Run a yt-dlp command, retrying transient failures before giving up: a 403
    (YouTube under load) backs off 3/6/9s, and a dropped connection (common on
    TikTok) retries immediately up to 3 times. Each class has its own counter, so
    a flapping connection can't loop forever. Any other failure returns at once --
    no point waiting on a bad URL or an unsupported site."""
    attempts_403 = 0
    attempts_drop = 0
    while True:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return result
        if _is_403(result.stderr) and attempts_403 < len(BACKOFFS_403):
            backoff = BACKOFFS_403[attempts_403]
            attempts_403 += 1
            print(f"[grab] got a 403; backing off {backoff}s and retrying "
                  f"(retry {attempts_403}/{len(BACKOFFS_403)})…", file=sys.stderr)
            time.sleep(backoff)
            continue
        if _is_connection_drop(result.stderr) and attempts_drop < IMMEDIATE_RETRIES:
            attempts_drop += 1
            print(f"[grab] connection dropped; immediate retry "
                  f"{attempts_drop}/{IMMEDIATE_RETRIES}…", file=sys.stderr)
            continue
        return result


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


def sanitize(text: str, limit: int) -> str:
    """Make text safe for a filename: strip odd chars, collapse underscore runs,
    and cap the length so the full name stays inside the 255-byte limit."""
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in text)
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe[:limit].strip(" -_")


def download_video(url: str) -> dict:
    platform = detect_platform(url)

    # Get metadata first
    result = run_ytdlp(
        ["yt-dlp", "--dump-json", "--no-download", url], timeout=60
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
    safe_title = sanitize(title, 100)
    if not safe_title:
        safe_title = "video"

    # Who posted it. yt-dlp has no field literally named "poster"; on YouTube the
    # channel comes back as uploader/channel, and other extractors vary, so fall
    # through the aliases. Appended to the filename so clips from the same account
    # group together. Skipped entirely when the extractor gives us nothing.
    poster = (info.get("uploader") or info.get("channel")
              or info.get("creator") or info.get("artist") or "")
    safe_poster = sanitize(poster, 60)
    stem = f"{safe_title} - {safe_poster}" if safe_poster else safe_title

    download_dir = os.path.expanduser("~/Downloads")
    # Use .mp4 directly since --merge-output-format mp4 forces the container.
    # Passing the source ext (e.g. .webm) here causes yt-dlp to write Title.webm.mp4
    # because the template's literal extension stays and the merge tacks on .mp4.
    output_path = os.path.join(download_dir, f"{stem}.mp4")

    # Download best quality
    result = run_ytdlp(
        ["yt-dlp", "-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4",
         "-o", output_path, url], timeout=600
    )

    if result.returncode != 0:
        return {"error": f"Download failed: {result.stderr.strip()}"}

    # Defensive fallback: if .mp4 isn't where we expected, find what yt-dlp actually wrote.
    if not os.path.exists(output_path):
        candidates = [f for f in os.listdir(download_dir)
                      if f.startswith(stem) and not f.endswith(".json")]
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

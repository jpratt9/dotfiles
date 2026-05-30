---
name: grab
description: Download a video from a URL (YouTube, TikTok, Instagram Reels, Facebook Reels) using yt-dlp
argument-hint: "<url>"
allowed-tools: Bash
---

Download a video from a supported platform URL using yt-dlp.

Supports: YouTube, TikTok, Instagram Reels, Facebook Reels, and any other yt-dlp-supported site.

## Steps

1. Run the downloader:
   ```
   python3 ~/.claude/skills/grab/scripts/download_video.py "$ARGUMENTS"
   ```

2. If the script returns an error, tell the user what went wrong (e.g. URL not supported, yt-dlp not installed, download failed).

3. If the download was successful, output:

   **Title:** (video title)
   **Platform:** (e.g. YouTube, TikTok, Instagram, Facebook)
   **Duration:** (duration if available)
   **File:** (path to downloaded file)

4. Do NOT open, play, or further process the file unless asked.

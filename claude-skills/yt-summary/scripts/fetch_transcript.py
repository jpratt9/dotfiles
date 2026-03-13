#!/usr/bin/env python3
"""Fetch YouTube video transcript using yt-dlp, with Groq Whisper fallback."""

import json
import subprocess
import sys
import re
import tempfile
import os


def fetch_transcript(url: str) -> dict:
    """Fetch transcript and metadata for a YouTube video."""

    # Get video metadata first
    result = subprocess.run(
        ["yt-dlp", "--dump-json", "--no-download", url],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        return {"error": f"Failed to fetch video info: {result.stderr.strip()}"}

    info = json.loads(result.stdout)
    title = info.get("title", "Unknown")
    channel = info.get("channel", "Unknown")
    duration = info.get("duration", 0)
    duration_str = f"{duration // 60}m {duration % 60}s"

    with tempfile.TemporaryDirectory() as tmpdir:
        # Try to get subtitles (prefer manual, fall back to auto-generated)
        out_path = os.path.join(tmpdir, "subs")

        for sub_flag in [
            ["--write-subs", "--sub-langs", "en.*,-live_chat", "--skip-download"],
            ["--write-auto-subs", "--sub-langs", "en.*,-live_chat", "--skip-download"],
        ]:
            result = subprocess.run(
                ["yt-dlp", *sub_flag, "--sub-format", "vtt/srt/best",
                 "--convert-subs", "srt", "-o", out_path, url],
                capture_output=True, text=True, timeout=60
            )

            srt_files = [f for f in os.listdir(tmpdir) if f.endswith(".srt")]
            if srt_files:
                srt_path = os.path.join(tmpdir, srt_files[0])
                with open(srt_path, "r", encoding="utf-8", errors="replace") as f:
                    raw_srt = f.read()

                transcript = parse_srt(raw_srt)
                return {
                    "title": title,
                    "channel": channel,
                    "duration": duration_str,
                    "transcript": transcript,
                }

        # No subtitles found — fall back to Groq Whisper transcription
        transcript = transcribe_with_groq(url, tmpdir, duration)
        if transcript:
            return {
                "title": title,
                "channel": channel,
                "duration": duration_str,
                "transcript": transcript,
                "source": "groq-whisper"
            }

    return {
        "title": title,
        "channel": channel,
        "duration": duration_str,
        "error": "No captions available and Groq transcription failed.",
    }


def transcribe_with_groq(url: str, tmpdir: str, duration: int) -> str | None:
    """Download audio and transcribe using Groq's Whisper API."""
    import requests

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None

    # Download audio
    audio_path = os.path.join(tmpdir, "audio.mp3")
    result = subprocess.run(
        ["yt-dlp", "-x", "--audio-format", "mp3", "-o", audio_path, url],
        capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0 or not os.path.exists(audio_path):
        return None

    # Check file size (Groq limit is 25MB)
    file_size = os.path.getsize(audio_path)
    if file_size > 25 * 1024 * 1024:
        # Too large — skip for now (could chunk in future)
        return None

    # Send to Groq
    try:
        with open(audio_path, "rb") as f:
            response = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": ("audio.mp3", f, "audio/mpeg")},
                data={"model": "whisper-large-v3"},
                timeout=120
            )

        if response.ok:
            return response.json().get("text", "")
    except Exception:
        pass

    return None


def parse_srt(srt_text: str) -> str:
    """Parse SRT content into clean text, removing timestamps and duplicates."""
    lines = []
    seen = set()
    for line in srt_text.splitlines():
        line = line.strip()
        # Skip sequence numbers, timestamps, and empty lines
        if not line or re.match(r"^\d+$", line) or re.match(r"\d{2}:\d{2}:", line):
            continue
        # Strip SRT/VTT tags
        clean = re.sub(r"<[^>]+>", "", line)
        clean = re.sub(r"\{[^}]+\}", "", clean)
        clean = clean.strip()
        if clean and clean not in seen:
            seen.add(clean)
            lines.append(clean)
    return " ".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: fetch_transcript.py <youtube_url>"}))
        sys.exit(1)

    result = fetch_transcript(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False))

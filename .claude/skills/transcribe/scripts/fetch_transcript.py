#!/usr/bin/env python3
"""Fetch transcript from a video/audio URL or local file using yt-dlp, with Groq Whisper fallback."""

import json
import subprocess
import sys
import re
import tempfile
import os


def is_local_file(path_or_url: str) -> bool:
    return os.path.exists(os.path.expanduser(path_or_url))


def fetch_transcript(url_or_path: str) -> dict:
    expanded = os.path.expanduser(url_or_path)
    if is_local_file(expanded):
        return fetch_local_transcript(expanded)
    return fetch_remote_transcript(url_or_path)


def fetch_remote_transcript(url: str) -> dict:
    """Fetch transcript for a remote URL (YouTube, TikTok, Instagram, Facebook, etc.)."""
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
        out_path = os.path.join(tmpdir, "subs")

        for sub_flag in [
            ["--write-subs", "--sub-langs", "en.*,-live_chat", "--skip-download"],
            ["--write-auto-subs", "--sub-langs", "en.*,-live_chat", "--skip-download"],
        ]:
            subprocess.run(
                ["yt-dlp", *sub_flag, "--sub-format", "vtt/srt/best",
                 "--convert-subs", "srt", "-o", out_path, url],
                capture_output=True, text=True, timeout=60
            )

            srt_files = [f for f in os.listdir(tmpdir) if f.endswith(".srt")]
            if srt_files:
                srt_path = os.path.join(tmpdir, srt_files[0])
                with open(srt_path, "r", encoding="utf-8", errors="replace") as f:
                    raw_srt = f.read()
                return {
                    "title": title,
                    "channel": channel,
                    "duration": duration_str,
                    "transcript": parse_srt(raw_srt),
                }

        # No subtitles — fall back to Groq Whisper
        transcript = transcribe_with_groq(url, tmpdir)
        if transcript:
            return {
                "title": title,
                "channel": channel,
                "duration": duration_str,
                "transcript": transcript,
                "source": "groq-whisper",
            }

    return {
        "title": title,
        "channel": channel,
        "duration": duration_str,
        "error": "No captions available and Groq transcription failed.",
    }


def fetch_local_transcript(file_path: str) -> dict:
    """Fetch transcript for a local video/audio file using Groq Whisper."""
    import requests

    title = os.path.splitext(os.path.basename(file_path))[0]

    # Get duration via ffprobe if available
    duration_str = "unknown"
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", file_path],
            capture_output=True, text=True, timeout=30
        )
        if probe.returncode == 0:
            duration = float(json.loads(probe.stdout).get("format", {}).get("duration", 0))
            duration_str = f"{int(duration) // 60}m {int(duration) % 60}s"
    except Exception:
        pass

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return {"title": title, "error": "Local files require GROQ_API_KEY for transcription."}

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, "audio.mp3")

        # Try yt-dlp first, then ffmpeg
        result = subprocess.run(
            ["yt-dlp", "-x", "--audio-format", "mp3", "-o", audio_path, file_path],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0 or not os.path.exists(audio_path):
            subprocess.run(
                ["ffmpeg", "-i", file_path, "-vn", "-acodec", "libmp3lame", "-q:a", "4", audio_path, "-y"],
                capture_output=True, text=True, timeout=300
            )

        if not os.path.exists(audio_path):
            return {"title": title, "error": "Failed to extract audio from local file."}

        if os.path.getsize(audio_path) > 25 * 1024 * 1024:
            return {"title": title, "error": "Audio file too large for Groq transcription (>25MB)."}

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
                return {
                    "title": title,
                    "duration": duration_str,
                    "transcript": response.json().get("text", ""),
                    "source": "groq-whisper",
                }
            return {"title": title, "error": f"Groq API error: {response.status_code} {response.text}"}
        except Exception as e:
            return {"title": title, "error": f"Transcription failed: {str(e)}"}


def transcribe_with_groq(url: str, tmpdir: str) -> str | None:
    """Download audio from URL and transcribe using Groq's Whisper API."""
    import requests

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None

    audio_path = os.path.join(tmpdir, "audio.mp3")
    result = subprocess.run(
        ["yt-dlp", "-x", "--audio-format", "mp3", "-o", audio_path, url],
        capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0 or not os.path.exists(audio_path):
        return None

    if os.path.getsize(audio_path) > 25 * 1024 * 1024:
        return None

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
        if not line or re.match(r"^\d+$", line) or re.match(r"\d{2}:\d{2}:", line):
            continue
        clean = re.sub(r"<[^>]+>", "", line)
        clean = re.sub(r"\{[^}]+\}", "", clean)
        clean = clean.strip()
        if clean and clean not in seen:
            seen.add(clean)
            lines.append(clean)
    return " ".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: fetch_transcript.py <url_or_file_path>"}))
        sys.exit(1)

    result = fetch_transcript(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False))

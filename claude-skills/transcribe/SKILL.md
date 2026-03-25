---
name: transcribe
description: Get the raw transcript of a video/audio file or URL (YouTube, TikTok, Instagram Reels, Facebook Reels)
argument-hint: "<url-or-file-path>"
allowed-tools: Bash
---

Get the raw transcript of a video or audio source without any summarization.

Supports: YouTube links, TikTok links, Instagram Reels links, Facebook Reels links, and local video/audio file paths.

## Steps

1. Run the transcript fetcher:
   ```
   python3 ~/.claude/skills/transcribe/scripts/fetch_transcript.py "$ARGUMENTS"
   ```

2. If the script returns an error, tell the user what went wrong (e.g. no captions available, missing GROQ_API_KEY for local files).

3. If the transcript was fetched successfully, output ONLY the raw transcript with minimal metadata:

   **Title:** (title if available)
   **Duration:** (duration if available)
   **Source:** (captions or groq-whisper)

   ---

   (raw transcript text, exactly as returned — no edits, no summarization)

4. Do NOT summarize, analyze, reformat, or add any commentary. Output the transcript verbatim.
5. Output everything directly to the console. Do not write any files.

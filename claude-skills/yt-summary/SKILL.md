---
name: yt-summary
description: Fetch and summarize a YouTube video transcript
argument-hint: "<youtube-url>"
allowed-tools: Bash
---

Summarize a YouTube video from its transcript.

## Steps

1. Run the transcript fetcher:
   ```
   python3 ~/.claude/skills/yt-summary/scripts/fetch_transcript.py "$ARGUMENTS"
   ```

2. If the script returns an error, tell the user what went wrong (e.g. no captions available).

3. If the transcript was fetched successfully, provide a summary with this format:

   **Title:** (video title)
   **Channel:** (channel name)
   **Duration:** (duration)

   ## Summary
   A concise 3-5 paragraph summary covering the main points, key arguments, and conclusions of the video. Focus on substance — what did the speaker actually say?

   ## Key Takeaways
   - Bullet list of 5-10 of the most important points or insights

4. Output everything directly to the console. Do not write any files.

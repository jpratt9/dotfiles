# Global Personal Memory

## Personal Preferences
- **TTS Integration:** Use Kokoro-ONNX via a Python wrapper script for high-fidelity neural TTS.
- **Auto-Speak:** By default, speak a concise summary or the core message of every response using Kokoro.
  - Command: `arch -arm64 python3 /Users/john/.gemini/skills/kokoro-tts/scripts/kokoro_tts.py "<TEXT>" "af_heart" | ffplay -f s16le -ar 24000 -nodisp -autoexit -`
  - *Note: Using ffplay for low-latency raw audio streaming at 24000Hz.*
  - *Available Voices: af_heart, af_bella, af_nicole, af_sky, am_adam, am_michael, bf_isabella, bf_alice, bm_george, bm_lewis.*

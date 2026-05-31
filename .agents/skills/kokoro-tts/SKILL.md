# Kokoro TTS Skill

This skill provides high-fidelity neural text-to-speech using the Kokoro-82M model via ONNX.

## Usage
- The core logic is located in `scripts/kokoro_tts.py`.
- It requires `kokoro-onnx` and `soundfile` Python packages.
- Model files are stored in `~/.gemini/kokoro/`.

## Constraints
- NO core message.
- ONLY read the LITERAL text.
- DO NOT SUMMARIZE.

## Voice Options
- `af_heart` (Default)
- `af_bella`
- `af_nicole`
- `af_sky`
- `am_adam`
- `am_michael`
- `bf_isabella`
- `bf_alice`
- `bm_george`
- `bm_lewis`

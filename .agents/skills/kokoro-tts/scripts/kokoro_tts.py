import sys
import numpy as np
from kokoro_onnx import Kokoro

def main():
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: python3 kokoro_tts.py <text> [voice]\n")
        sys.exit(1)

    text = sys.argv[1]
    voice = sys.argv[2] if len(sys.argv) > 2 else "af_heart"
    
    # Paths for the model and voices
    model_path = "/Users/john/.gemini/kokoro/kokoro-v1.0.onnx"
    voices_path = "/Users/john/.gemini/kokoro/voices-v1.0.bin"

    try:
        kokoro = Kokoro(model_path, voices_path)
        samples, sample_rate = kokoro.create(
            text,
            voice=voice,
            speed=1.0,
            lang="en-us"
        )
        
        # Convert float32 samples to int16 for PCM
        # Note: we need to handle clipping if samples exceed 1.0/-1.0
        audio_int16 = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
        
        # Write raw PCM to stdout
        sys.stdout.buffer.write(audio_int16.tobytes())
        
    except Exception as e:
        sys.stderr.write(f"Error: {str(e)}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()

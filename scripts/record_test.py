from pathlib import Path
import wave, numpy as np
from app.audio.recorder import mic_stream

out = wave.open("test.wav", "wb")
out.setnchannels(1)
out.setsampwidth(2)     # 16-bit
out.setframerate(16_000)

print("Speak for 5 seconds…")
for i, chunk in enumerate(mic_stream()):
    out.writeframes(chunk.pcm.tobytes())
    if i >= (1000 // 30) * 5:    # ≈ 5 s of 30 ms chunks
        break

out.close()
print("Saved → test.wav")

import wave, numpy as np, pathlib
from app.audio.recorder import AudioChunk

def wav_stream(path: str, block_ms: int = 30):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        frame_len = sr * block_ms // 1000
        t = 0.0
        while pcm := w.readframes(frame_len):
            yield AudioChunk(
                pcm=np.frombuffer(pcm, dtype=np.int16),
                t0=t,
            )
            t += block_ms / 1000

# Example: just dump timestamps
for chunk in wav_stream("sounds/basic_commands.wav"):
    print(chunk.t0, chunk.pcm.shape)

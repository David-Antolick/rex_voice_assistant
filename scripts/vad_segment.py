# scripts/vad_segment.py

import os
os.environ["TORCH_CPP_LOG_LEVEL"] = "ERROR"

import wave, numpy as np
from pathlib import Path
import torch
# silero hub load
model, utils = torch.hub.load(
    'snakers4/silero-vad',
    'silero_vad',
    force_reload=False
)
get_speech_timestamps, _, _, _, _ = utils

# 1. Read entire WAV
base = Path(__file__).parent.parent
wav_path = base / "sounds" / "basic_commands.wav"
with wave.open(str(wav_path), "rb") as w:
    sr = w.getframerate()        # should be 16000
    raw = w.readframes(w.getnframes())
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

# 2. Detect all speech segments
segments = get_speech_timestamps(
    audio,
    model,
    sampling_rate=sr,
    threshold=0.5,       # you can lower this if you still miss speech
    return_seconds=True
)
print("Detected speech segments (s):", segments)

# 3. Stream 30 ms chunks and tag
block_ms = 30
frame = sr * block_ms // 1000
t = 0.0
i = 0
print("\nChunk tags:")
while True:
    start = i * frame
    end   = start + frame
    chunk = audio[start:end]
    if len(chunk) < frame:
        break

    # overlap test
    is_speech = any(seg['start'] < t + block_ms/1000 and seg['end'] > t
                    for seg in segments)
    tag = "1" if is_speech else "0"
    print(f"{t:>5.2f}s → {tag}")
    i += 1
    t += block_ms/1000

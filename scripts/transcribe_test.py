# scripts/transcribe_test.py

import wave
import numpy as np
import torch
from pathlib import Path
from faster_whisper import WhisperModel

# Load Silero VAD
vad_model, vad_utils = torch.hub.load(
    'snakers4/silero-vad',
    'silero_vad',
    force_reload=False
)
get_speech_timestamps, _, _, _, _ = vad_utils

# Load Whisper
device = "cuda" if torch.cuda.is_available() else "cpu"
model = WhisperModel(
    "medium.en",
    device=device,
    compute_type="int8_float16"
)

# Read your WAV
base     = Path(__file__).parent.parent
wav_path = base / "sounds" / "basic_commands.wav"
with wave.open(str(wav_path), "rb") as w:
    sr        = w.getframerate()
    audio_int = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)

# Find speech segments
audio_f32 = audio_int.astype(np.float32) / 32768.0
segments, info = model.transcribe(
    str(wav_path),
    language="en",     # explicit
    beam_size=5,
    temperature=[0.0]
)
for seg in segments:
    print(f"{seg.start:.2f}–{seg.end:.2f}s → {seg.text.strip()}")

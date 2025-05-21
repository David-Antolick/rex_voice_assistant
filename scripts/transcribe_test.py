# scripts/transcribe_test.py

import os
os.environ["TORCH_CPP_LOG_LEVEL"] = "ERROR"

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
device = "cuda:0" if torch.cuda.is_available() else "cpu"
stt = WhisperModel(
    "tiny.en",
    device="cuda",          # GPU backend
    device_index=0,         # pick GPU 0 (or loop over devices)
    compute_type="int8_float16"  # use FP16 for best speed
)

# Read in your resampled WAV
base     = Path(__file__).parent.parent
wav_path = base / "sounds" / "basic_commands.wav"
with wave.open(str(wav_path), "rb") as w:
    sr         = w.getframerate()                   # should be 16000
    raw        = w.readframes(w.getnframes())
    audio_int  = np.frombuffer(raw, dtype=np.int16)
    audio_f32  = audio_int.astype(np.float32) / 32768.0

# VAD over the full audio
segments = get_speech_timestamps(
    audio_f32,
    vad_model,
    sampling_rate=sr,
    threshold=0.5,
    return_seconds=True
)
print("Detected speech segments (s):", segments, "\n")

# Transcribe each segment
print("Transcriptions:")
for seg in segments:
    # slice the int16 waveform
    start_sample = int(seg['start'] * sr)
    end_sample   = int(seg['end']   * sr)
    chunk_int    = audio_int[start_sample:end_sample]

    # WhisperModel.transcribe returns a list of segments
    results, _ = stt.transcribe(chunk_int, sr)
    text = " ".join([r.text.strip() for r in results]).strip()

    print(f"{seg['start']:.2f}–{seg['end']:.2f}s → {text}")

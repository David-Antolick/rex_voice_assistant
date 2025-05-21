# stand_app/vad_detect.py
"""Standalone Silero‑VAD detector for pre‑processed audio.

Usage examples

# 1) Directly on a WAV file (mono or stereo) – internally normalizes
python vad_detect.py sounds/basic_commands.wav

# 2) On a .npy file previously created by preprocess_wav.py
python vad_detect.py stand_app/outputs/processed_audio.npy --npy

Outputs

* Prints a JSON list of speech segments: [{"start": float, "end": float}, ...]
* Emits a visual timeline to stdout: "0.00–0.03 0", where 1 = speech, 0 = silence.
"""
from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path
from typing import List

import numpy as np
import torch

#  Silero VAD 
model, utils = torch.hub.load(
    repo_or_dir="snakers4/silero-vad",
    model="silero_vad",
    force_reload=False,
)
get_speech_timestamps, _, _, _, _ = utils

TARGET_SR = 16_000
BLOCK_MS = 30


def load_audio(path: Path, is_npy: bool = False) -> np.ndarray:
    """Return float32 PCM in [-1,1] at 16 kHz mono."""
    if is_npy:
        audio = np.load(path).astype(np.float32)
        return audio

    # WAV fallback
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        n_frames = wf.getnframes()
        n_channels = wf.getnchannels()
        audio_i16 = np.frombuffer(wf.readframes(n_frames), dtype=np.int16)
        if n_channels == 2:
            audio_i16 = audio_i16.reshape(-1, 2).mean(axis=1).astype(np.int16)

    if sr != TARGET_SR:
        from scipy.signal import resample_poly
        from math import gcd

        g = gcd(sr, TARGET_SR)
        up, down = TARGET_SR // g, sr // g
        audio_i16 = resample_poly(audio_i16, up, down)

    return (audio_i16.astype(np.float32)) / 32768.0


def detect_segments(audio: np.ndarray) -> List[dict]:
    return get_speech_timestamps(
        audio,
        model,
        sampling_rate=TARGET_SR,
        threshold=0.5,
        return_seconds=True,
    )


def chunk_timeline(audio: np.ndarray, segments: List[dict], args):
    frame = TARGET_SR * BLOCK_MS // 1000
    t = 0.0
    i = 0
    while True :
        start = i * frame
        end = start + frame
        if end > len(audio):
            break
        if args.verbose:
            is_speech = any(seg["start"] < t + BLOCK_MS / 1000 and seg["end"] > t for seg in segments)
            print(f"{t:5.2f}–{t + BLOCK_MS / 1000:5.2f} {'1' if is_speech else '0'}")
        i += 1
        t += BLOCK_MS / 1000


def main():
    ap = argparse.ArgumentParser(description="Run Silero VAD on an audio file")
    ap.add_argument("--save", type=Path, help="Optional path to save speech segments as JSON")
    ap.add_argument("audio", type=Path, help=".wav or .npy file")
    ap.add_argument("--npy", action="store_true", help="Input is a .npy file")
    ap.add_argument("--verbose", action="store_true", help="Enable detailed readout of VAD timeline")
    args = ap.parse_args()

    audio = load_audio(args.audio, is_npy=args.npy)
    segments = detect_segments(audio)

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        with open(args.save, "w") as f:
            json.dump(segments, f, indent=2)
            print('Chunks Saved to: ', args.save.parent)
    else:
        print(json.dumps(segments, indent=2))

    chunk_timeline(audio, segments, args)


if __name__ == "__main__":
    main()

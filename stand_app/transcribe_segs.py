# stand_app/transcribe_segments.py
"""
Transcribe speech segments from a preprocessed audio file using Whisper.

Usage:
  python transcribe_segments.py audio.npy segments.json

Inputs:
  - audio.npy: float32 mono audio at 16kHz (output of preprocess_wav.py)
  - segments.json: list of {"start": float, "end": float} timestamps (output of vad_detect.py)

Output:
  - Prints start–end and transcription for each speech segment

Dependencies:
  - faster-whisper (install via pip)


run with:
python stand_app/transcribe_segs.py --inp stand_app/outputs/processed_audio.npy --segs stand_app/outputs/speech_segments.json --out stand_app/outputs/transcript.csv


"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

TARGET_SR = 16000


def load_inputs(audio_path: Path, seg_path: Path):
    audio = np.load(audio_path)
    with open(seg_path) as f:
        segments = json.load(f)
    return audio, segments


def run_whisper(model: WhisperModel, audio: np.ndarray, segments: list[dict], args):
    lines = []
    for seg in segments:
        pad = int(0.2 * TARGET_SR)  # 200 ms
        s = max(0, int(seg["start"] * TARGET_SR) - pad)
        e = min(len(audio), int(seg["end"] * TARGET_SR) + pad)
        segment_audio = audio[s:e]


        # Save to temporary WAV if needed by whisper, but faster-whisper supports np.ndarray
        result, _ = model.transcribe(segment_audio, language="en", beam_size=5, temperature=0.0)

        for chunk in result:
            line = f"{seg['start']:.2f}, {seg['end']:.2f}, {chunk.text.strip()}"
            print(line)
            lines.append(line)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w") as f:
            f.write("\n".join(lines))
        print("Transcript saved to", args.out)

            


def main():
    ap = argparse.ArgumentParser(description="Transcribe segments using Whisper")
    ap.add_argument("--inp", type=Path, help="Path to .npy audio")
    ap.add_argument("--segs", type=Path, help="Path to segment JSON")
    ap.add_argument("--out", type=Path, help="Optional path to save transcript with timestamps")

    args = ap.parse_args()

    model = WhisperModel("medium.en", device="cuda", compute_type="int8")
    audio, segments = load_inputs(args.inp, args.segs)

    run_whisper(model, audio, segments, args)


if __name__ == "__main__":
    main()

# stand_app/preprocess_wav.py
"""Pre‑processing utility for VAD‑ready audio.

Runs as a **stand‑alone** script:

```bash
python preprocess_wav.py path/to/input.wav  
python preprocess_wav.py sounds/basic_commands.wav --out audio.npy --target-sr 16000
```

Features
========
1. **Universal input**: accepts any mono/stereo WAV.
2. **Mono mix‑down**: sums stereo → mono (average).
3. **Resample**: converts to target sample‑rate (default 16 kHz) using polyphase filter from ``scipy.signal``.
4. **Normalize**: converts ``int16`` → ``float32`` in **[-1.0, 1.0]`` – Silero VAD expects this.
5. **Optional save**: writes NumPy ``.npy`` file for downstream scripts.
6. **JSON metadata**: prints a short JSON summary to stdout for quick inspection.

Dependencies
------------
* ``numpy``
* ``scipy`` (only ``scipy.signal``) – install via ``pip install scipy``.

The script purposefully avoids heavyweight deps (librosa/torchaudio) to keep the
stand‑alone test environment minimal.
"""
from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path
from typing import Tuple

import numpy as np
from scipy.signal import resample_poly

TARGET_DTYPE = np.float32


def read_wav(path: Path) -> Tuple[np.ndarray, int]:
    """Load a WAV file → (int16 np.ndarray, sample_rate).

    We use the built‑in *wave* module because it has zero external
    dependencies and is adequate for PCM WAV reading.
    """
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        n_frames = wf.getnframes()
        n_channels = wf.getnchannels()
        audio = np.frombuffer(wf.readframes(n_frames), dtype=np.int16)
        if n_channels == 2:
            audio = audio.reshape(-1, 2).mean(axis=1).astype(np.int16)
    return audio, sr


def resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resample *audio* from *orig_sr* → *target_sr* using polyphase method."""
    if orig_sr == target_sr:
        return audio
    # Use greatest common divisor to compute up/down factors
    from math import gcd

    g = gcd(orig_sr, target_sr)
    up = target_sr // g
    down = orig_sr // g
    return resample_poly(audio, up, down).astype(audio.dtype)


def normalize_int16(audio: np.ndarray) -> np.ndarray:
    """Convert int16 PCM to float32 in [-1.0, 1.0]."""
    return (audio.astype(TARGET_DTYPE)) / 32768.0


def save_npy(audio: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, audio)


def main():
    parser = argparse.ArgumentParser(description="Preprocess WAV for VAD/ASR")
    parser.add_argument("wav", type=Path, help="Input WAV path")
    parser.add_argument("--out", type=Path, default='stand_app/outputs/processed_audio.npy', help="Optional .npy output path")
    parser.add_argument("--target-sr", type=int, default=16_000, help="Target sample‑rate (Hz)")
    args = parser.parse_args()

    if not args.wav.exists():
        raise FileNotFoundError(args.wav)

    # Load
    audio_i16, sr = read_wav(args.wav)

    # Resample if needed
    audio_i16 = resample(audio_i16, sr, args.target_sr)
    sr = args.target_sr

    # Normalize
    audio_f32 = normalize_int16(audio_i16)

    # Optionally save
    if args.out:
        save_npy(audio_f32, args.out.with_suffix(".npy"))

    # Print summary
    meta = {
        "input_path": str(args.wav),
        "samples": int(audio_f32.shape[0]),
        "duration_s": round(audio_f32.shape[0] / sr, 3),
        "sample_rate": sr,
        "dtype": str(audio_f32.dtype),
        "saved_to": str(args.out.with_suffix(".npy")) if args.out else None,
    }
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()

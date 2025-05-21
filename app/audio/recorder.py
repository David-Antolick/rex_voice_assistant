# app/audio/recorder.py
# Yields 16 kHz mono audio in fixed-length chunks.

from __future__ import annotations
import sounddevice as sd
import numpy as np
from dataclasses import dataclass
from typing import Iterator

@dataclass
class AudioChunk:
    pcm: np.ndarray   # int16 samples, shape = (n,)
    t0: float         # chunk start-time in seconds

def mic_stream(
    block_ms: int = 30,
    sample_rate: int = 16_000,
    device: int | str | None = None,
) -> Iterator[AudioChunk]:
    """Generator: microphone → consecutive AudioChunk objects."""
    frame_len = int(sample_rate * block_ms / 1000)

    with sd.InputStream(
        samplerate=sample_rate,
        blocksize=frame_len,
        channels=1,
        dtype="int16",
        device=device,
    ) as stream:
        while True:
            pcm, _ = stream.read(frame_len)
            yield AudioChunk(
                pcm=pcm.flatten(),
                t0=sd.get_stream_time(),
            )

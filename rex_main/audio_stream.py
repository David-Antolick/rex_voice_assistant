"""audio_stream.py
A non-blocking microphone capture helper for the REX voice-assistant.

Usage example (inside your main asyncio program):

    audio_q = asyncio.Queue()
    async with AudioStream(audio_q):
        ...  # other coroutines (VAD, Whisper, etc.)

Each item placed on *audio_q* is a 1-D NumPy array of float32 PCM samples
(normalised to -1.0…1.0) exactly *frame_ms* milliseconds long.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Optional

import numpy as np
import sounddevice as sd

__all__ = ["AudioStream"]


class AudioStream:
    """Asynchronously push frames from the default microphone into a queue.

    Parameters
    ----------
    queue : asyncio.Queue[np.ndarray]
        Destination queue that will receive PCM blocks.
    samplerate : int, default 16_000
        Target sampling rate (Hz).  Make sure downstream models agree.
    frame_ms : int, default 40
        Duration of each frame in milliseconds.  Values ≤ 30ms keep VAD latency low.
    """

    def __init__(self, queue: asyncio.Queue, *, samplerate: int = 16_000, frame_ms: int = 32):
        self.queue = queue
        self.samplerate = samplerate
        self.frame_len = int(samplerate * frame_ms / 1000)
        self.frame_ms = frame_ms
        self._stream: Optional[sd.InputStream] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_evt = asyncio.Event()

    # Public async context-manager helpers
    async def __aenter__(self):
        self._loop = asyncio.get_running_loop()
        self._start_stream()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        # signal _reader() to stop and wait for clean shutdown
        self._stop_evt.set()
        await self._reader_task

        if self._stream is not None:
            self._stream.stop()
            self._stream.close()

   # Internal helpers
    def _start_stream(self):
        """Launch a background ffmpeg process and its reader coroutine.

        We use PulseAudio’s ‘default’ source and write 16-bit little-endian
        PCM to stdout so no temporary files are created.
        """
        import subprocess, shlex

        # Spawn ffmpeg → raw PCM on stdout
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-loglevel", "quiet",          # ← *pair stays together*
            "-f", "pulse", "-i", "default",
            "-ac", "1", "-ar", str(self.samplerate),
            "-f", "s16le", "pipe:1"        # raw int16 to stdout
        ]

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            bufsize=0  # unbuffered so we can read exact frame sizes
        )

        if self._proc.stdout is None:
            raise RuntimeError("ffmpeg did not expose stdout")

        # background coroutine that reads from ffmpeg stdout
        self._reader_task = asyncio.create_task(self._reader())

    async def _reader(self):
        bytes_needed = self.frame_len * 2          # 1024 bytes for 512 samples
        buf = bytearray()

        while not self._stop_evt.is_set():
            chunk = await asyncio.get_running_loop().run_in_executor(
                None, self._proc.stdout.read, bytes_needed - len(buf)
            )
            if not chunk:                          # ffmpeg exited
                break
            buf.extend(chunk)

            if len(buf) == bytes_needed:
                pcm = np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0
                await self.queue.put(pcm)
                buf.clear()                        # start next frame

        with contextlib.suppress(ProcessLookupError):
            self._proc.terminate()



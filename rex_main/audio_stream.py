"""audio_stream.py
A non-blocking microphone capture helper for the REX voice-assistant.

Usage example (inside your main asyncio program):

    audio_q = asyncio.Queue()
    async with AudioStream(audio_q):
          # other coroutines (VAD, Whisper, etc.)

Each item placed on *audio_q* is a 1-D NumPy array of float32 PCM samples
(normalised to -1.0…1.0) exactly *frame_ms* milliseconds long. (default 32ms,512 samples at 16kHz)
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Optional
import subprocess, shlex
import numpy as np
import sounddevice as sd

import logging
logger = logging.getLogger(__name__)

__all__ = ["AudioStream"]


class AudioStream:
    """Asynchronously push frames from the default microphone into a queue.

    Parameters
    ----------
    queue : asyncio.Queue[np.ndarray]
        Destination queue that will receive PCM blocks.
    samplerate : int, default 16_000
        Target sampling rate (Hz).  Make sure downstream models agree.
    frame_ms : int, default 32
        Duration of each frame in milliseconds. Must be consistent with VAD framework.
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

        We use PulseAudio's 'default' source and write 16-bit little-endian
        PCM to stdout so no temporary files are created.
        """


        # show configured frame size & rates
        logger.debug(
            "AudioStream starting: samplerate=%d Hz, frame_ms=%d ms → frame_len=%d samples",
             self.samplerate, self.frame_ms, self.frame_len,
        )   
        
        # inspect sounddevice input config
        default_input, _ = sd.default.device

        if default_input is None or default_input < 0:
            # you’re using ffmpeg’s “default” source, so sounddevice hasn’t picked one
            logger.debug(
                "No sounddevice default input device (got %s); FFmpeg default will be used",
                default_input,
            )
            # list actual hardware mics in case you want to bind one later
            devices = sd.query_devices()
            inputs = [
                (i, d["name"]) 
                for i, d in enumerate(devices) 
                if d.get("max_input_channels", 0) > 0
            ]
            logger.debug("Available input devices: %s", inputs)
        else:
            # real default is set—confirm it
            try:
                dev_info = sd.query_devices(default_input, kind="input")
                logger.debug(
                    "sounddevice default input device [%d]: %s",
                    default_input,
                    dev_info.get("name", dev_info),
                )
            except Exception as e:
                logger.debug(
                    "Error querying input device %d: %s",
                    default_input,
                    e,
                )


        # Spawn ffmpeg → raw PCM on stdout
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-loglevel", "quiet",          # ← pair stays together
            "-f", "pulse", "-i", "default",
            "-ac", "1", "-ar", str(self.samplerate),
            "-f", "s16le", "pipe:1"        # raw int16 to stdout
        ]

        logger.debug("ffmpeg cmd: %s", " ".join(cmd))
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            bufsize=0  # unbuffered
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



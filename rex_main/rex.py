"""rex.py
Entry-point for the REX voice assistant.

Run inside the dev-container (with PulseAudio / CUDA exposed):

    python -m rex_main.rex

Press **Ctrl-C** to exit cleanly.
"""

from __future__ import annotations

import argparse
import asyncio
import signal
from pathlib import Path
from typing import Optional
import numpy as np

from rex_main.audio_stream import AudioStream
from rex_main.vad_stream import SileroVAD
from rex_main.whisper_worker import WhisperWorker
from rex_main.matcher import dispatch_command

import logging
logger = logging.getLogger("rex")


# CLI

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the REX voice assistant")
    p.add_argument(
        "--model",
        default="small.en",
        help="Whisper model size (tiny|base|small|medium|large or distil-*)",
    )
    p.add_argument(
        "--device",
        default="cuda",
        choices=["cuda", "cpu", None],
        help="Force device; default=auto",
    )
    p.add_argument(
        "--beam",
        type=int,
        default=1,
        help="Beam size for Whisper decoding (1 is fastest)",
    )
    p.add_argument(
        "--log_file",
        type=str,
        default="rex_main/logs/rex_log.log",
        help="Path to write rotating logs",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Verbose logging",
    )
    return p.parse_args(argv)


# Main orchestration

async def main(opts: argparse.Namespace):

    """Main entry-point coroutine."""

   # ___ Logging setup ___
    root = logging.getLogger()
    # Remove any existing handlers
    for h in root.handlers[:]:
        root.removeHandler(h)
    level = logging.DEBUG if opts.debug else logging.INFO
    root.setLevel(level)

    # Create a common formatter
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    formatter = logging.Formatter(fmt)

    # Console handler (always)
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # Rotating file handler
    if opts.log_file:
        from logging.handlers import RotatingFileHandler
        fileh = RotatingFileHandler(
            opts.log_file,
            maxBytes=2_000_000,
            backupCount=2,
        )
        fileh.setLevel(level)
        fileh.setFormatter(formatter)
        root.addHandler(fileh)
        
    # Suppress other loggers to warning level
    logging.getLogger("torio._extension.utils").setLevel(logging.WARNING)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
    # ___ End logging setup ___

    # Queues
    audio_q: "asyncio.Queue[np.ndarray]" = asyncio.Queue(maxsize=50)
    speech_q: "asyncio.Queue[np.ndarray]" = asyncio.Queue(maxsize=10)
    text_q: "asyncio.Queue[str]" = asyncio.Queue(maxsize=10)

    async with AudioStream(audio_q):
        vad = SileroVAD(audio_q, speech_q)
        whisper = WhisperWorker(
            speech_q,
            text_q,
            model_name=opts.model,
            device=opts.device,
            beam_size=opts.beam,
        )

        tasks = [
            asyncio.create_task(vad.run(), name="vad"),
            asyncio.create_task(whisper.run(), name="whisper"),
            asyncio.create_task(dispatch_command(text_q), name="matcher"),
        ]

        # Handle Ctrl-C for graceful shutdown
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, _cancel_tasks, tasks)

        # Wait until the first task raises (ideally never) or is cancelled
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Shutdown requested - waiting for tasks to finish...")
            await asyncio.gather(*tasks, return_exceptions=True)


def _cancel_tasks(tasks: list[asyncio.Task]):
    logger.info("Cancelling %d tasks…", len(tasks))
    for t in tasks:
        t.cancel()


# Entry-point
if __name__ == "__main__":
    asyncio.run(main(parse_args()))

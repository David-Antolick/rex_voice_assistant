"""rex.py
Entry-point for the REX voice assistant.

Run with the CLI:
    rex           # Start the assistant
    rex setup     # Interactive setup wizard
    rex status    # Show configuration status

Or directly:
    python -m rex_main.rex

Press **Ctrl-C** to exit cleanly.
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path
from typing import Optional, Any
import numpy as np

from rex_main.audio_stream import AudioStream
from rex_main.vad_stream import SileroVAD
from rex_main.whisper_worker import WhisperWorker
from rex_main.matcher import dispatch_command
from rex_main.metrics_printer import print_metrics_loop

import logging
logger = logging.getLogger("rex")


# CLI

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the REX voice assistant")
    p.add_argument(
        "--model",
        default="medium",
        help="Whisper model size (tiny|base|small|medium|large or distil-*)",
    )
    p.add_argument(
        "--device",
        default="auto",
        choices=["cuda", "cpu", "auto"],
        help="Device for Whisper model (auto will use CPU unless --device cuda is explicit)",
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

async def run_assistant(opts: Any, config: Optional[dict] = None):
    """Main entry-point coroutine for the voice assistant.

    Args:
        opts: Options object with model, device, beam, log_file, debug attributes
        config: Optional configuration dictionary (used for pulse_server, etc.)
    """

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

    # Check service configuration and show startup info
    active_service = "none"
    if config:
        active_service = config.get("services", {}).get("active", "none")

    logger.info("=" * 50)
    logger.info("REX Voice Assistant starting...")
    logger.info("Model: %s | Device: %s | Beam: %d", opts.model, opts.device, opts.beam)
    logger.info("Active service: %s", active_service)

    if active_service == "none":
        logger.warning("No music service configured - running in transcription-only mode")
        logger.warning("Run 'rex setup' to configure YTMD or Spotify")

    logger.info("=" * 50)
    logger.info("Listening... (Press Ctrl+C to exit)")

    # Queues
    audio_q: "asyncio.Queue[np.ndarray]" = asyncio.Queue(maxsize=50)
    speech_q: "asyncio.Queue[np.ndarray]" = asyncio.Queue(maxsize=10)
    text_q: "asyncio.Queue[str]" = asyncio.Queue(maxsize=10)

    # Get pulse_server from config if available
    pulse_server = None
    if config:
        pulse_server = config.get("audio", {}).get("pulse_server")

    # Determine VAD silence timeout based on low-latency mode
    low_latency = getattr(opts, 'low_latency', False)
    vad_silence_ms = 250 if low_latency else 400

    if low_latency:
        logger.info("Low-latency mode enabled (VAD timeout: %dms)", vad_silence_ms)

    async with AudioStream(audio_q, pulse_server=pulse_server):
        vad = SileroVAD(audio_q, speech_q, silence_ms=vad_silence_ms)
        whisper = WhisperWorker(
            speech_q,
            text_q,
            model_name=opts.model,
            device=opts.device,
            beam_size=opts.beam,
        )

        # Pre-warm Whisper model to eliminate cold-start latency
        whisper.warmup()

        tasks = [
            asyncio.create_task(vad.run(), name="vad"),
            asyncio.create_task(whisper.run(), name="whisper"),
            asyncio.create_task(dispatch_command(text_q), name="matcher"),
            asyncio.create_task(print_metrics_loop(30), name="metrics_printer"),
        ]

        # Handle Ctrl-C for graceful shutdown
        # Note: add_signal_handler doesn't work on Windows, but KeyboardInterrupt is caught
        if sys.platform != "win32":
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


# Legacy alias for backwards compatibility
main = run_assistant


# Entry-point
if __name__ == "__main__":
    asyncio.run(run_assistant(parse_args()))

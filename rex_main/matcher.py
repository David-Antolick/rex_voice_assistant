"""
matcher.py
Regex-based command dispatcher for the REX assistant.

Usage inside your main program (rex.py):

    text_q = asyncio.Queue()
    asyncio.create_task(dispatch_command(text_q))

Each message pulled from *text_q* is compared against the patterns below.
On the first match the corresponding function inside *commands.py* is
invoked (synchronously for now; wrap in run_in_executor if commands turn
CPU-heavy).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Callable, Iterable

import rex_main.commands as commands

__all__ = ["dispatch_command"]

logger = logging.getLogger(__name__)


# Common helpers (for robustness)
_END   = r"[.!?\s]*$"              # trailing punctuation / spaces
_WORD  = r"\s*"                    # surrounding spaces

COMMAND_PATTERNS: list[tuple[re.Pattern[str], str]] = [

    # YTMD: play / pause
    (re.compile(rf"^{_WORD}stop\s+music{_WORD}{_END}",  re.I), "stop_music"),
    (re.compile(rf"^{_WORD}play\s+music{_WORD}{_END}", re.I), "play_music"),


    # YTMD: track navigation
    (re.compile(rf"^{_WORD}(?:next|skip){_WORD}{_END}", re.I), "next_track"),
    (re.compile(rf"^{_WORD}(?:last|previous){_WORD}{_END}", re.I), "previous_track"),
    (re.compile(rf"^{_WORD}restart{_WORD}{_END}", re.I), "restart_track"),
    (re.compile(rf"^{_WORD}search\s+(.+?)(?:\s+by\s+(.+?))?{_END}", re.I), "search_song"),


    # YTMD: volume control
    (re.compile(rf"^{_WORD}volume up{_END}",   re.I), "volume_up"),
    (re.compile(rf"^{_WORD}volume down{_END}", re.I), "volume_down"),
    (re.compile(rf"^{_WORD}volume\s+(\d{{1,3}}){_WORD}{_END}", re.I), "set_volume"),


    # YTMD: like / dislike
    (re.compile(rf"^{_WORD}like{_WORD}{_END}",    re.I), "like"),
    (re.compile(rf"^{_WORD}dislike{_WORD}{_END}", re.I), "dislike"),

    # YTMD: other commands
    (re.compile(rf"^{_WORD}this\s+is\s+so\s+sad{_WORD}{_END}", re.I), "so_sad"),

    
    # Switching to other apps
    (re.compile(rf"^{_WORD}switch\s+to\s+spotify{_END}", re.I), "configure_spotify"),
    (re.compile(rf"^{_WORD}switch\s+to\s+youtube\s+music{_END}", re.I), "configure_ytmd"),

]


# Public coroutine
async def dispatch_command(text_queue: "asyncio.Queue[str]"):  
    """Forever task that reads recognised text and triggers handlers."""
    logger.info("dispatch_command started - awaiting recognized text")

    while True:
        text = (await text_queue.get()).strip()
        logger.debug("Received text: %s", text)

        matched = False
        for pattern, func_name in COMMAND_PATTERNS:
            m = pattern.match(text)
            if m:
                matched = True
                logger.info("Matched command '%s'", func_name)
                _call_handler(func_name, m.groups())
                break

        if not matched:
            logger.debug("No command matched for input: %r", text)

        text_queue.task_done()


# Helpers

def _call_handler(func_name: str, args: tuple[str, ...]):
    """Look up *commands.func_name* and invoke it with *args*."""

    func: Callable[..., None] | None = getattr(commands, func_name, None)
    if not callable(func):
        logger.error("Handler '%s' not found in commands.py", func_name)
        return

    try:
        func(*args)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error while executing '%s': %s", func_name, exc)
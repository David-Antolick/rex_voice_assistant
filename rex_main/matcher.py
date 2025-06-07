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
logger.setLevel(logging.INFO)

# Command patterns

_ACTIVATION = r"(?:hey\s+rex[,\s]+)?"  # optional wake-word prefix

COMMAND_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(fr"^{_ACTIVATION}stop\s+music[.! ]*$", re.I), "stop_music"),
    (re.compile(fr"^{_ACTIVATION}start\s+music[.! ]*$", re.I), "start_music"),
    (
        re.compile(fr"^{_ACTIVATION}play\s+(.+?)\s+by\s+([\w\s]+)[.! ]*$", re.I),
        "play_song",
    ),
    (
        re.compile(fr"^{_ACTIVATION}play\s+(.+)[.! ]*$", re.I),
        "play_song",
    ),
]


# Public coroutine
async def dispatch_command(text_queue: "asyncio.Queue[str]"):  # noqa: C901 – keep simple
    """Forever task that reads recognised text and triggers handlers."""

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
            logger.debug("No command matched: %s", text)

        text_queue.task_done()


# Helpers

def _call_handler(func_name: str, args: tuple[str, ...]):
    """Look up *commands.func_name* and invoke it with *args*."""

    func: Callable[..., None] | None = getattr(commands, func_name, None)
    if not callable(func):
        logger.error("Handler '%s' not found in commands.py", func_name)
        return

    try:
        func(*args)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001 – want broad catch for assistant safety
        logger.exception("Error while executing '%s': %s", func_name, exc)
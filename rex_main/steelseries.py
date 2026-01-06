# steelseries.py - SteelSeries GG Moments integration
"""
SteelSeries GG Moments integration for REX voice assistant.

Uses the GameSense SDK to trigger clips via the local SteelSeries GG server.
See: https://github.com/SteelSeries/gamesense-sdk/blob/master/doc/api/sending-moments-events.md

Setup:
1. SteelSeries GG must be running
2. Moments must be enabled and recording
3. User must enable REX autoclipping in GG: Settings > Moments > Apps > REX
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy imports
_requests = None


def _get_requests():
    """Lazy-load requests to avoid import overhead."""
    global _requests
    if _requests is None:
        import requests
        _requests = requests
    return _requests


def _get_gamesense_address() -> Optional[str]:
    """
    Read the GameSense server address from coreProps.json.

    Returns the address (e.g., "127.0.0.1:51250") or None if not found.
    """
    # Check both possible locations
    paths = [
        os.path.expandvars(r"%PROGRAMDATA%\SteelSeries\SteelSeries Engine 3\coreProps.json"),
        os.path.expandvars(r"%PROGRAMDATA%\SteelSeries\GG\coreProps.json"),
    ]

    for path in paths:
        try:
            with open(path, "r") as f:
                data = json.load(f)
                if "address" in data:
                    return data["address"]
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            continue

    return None


class SteelSeriesMoments:
    """
    Client for SteelSeries GG Moments autoclipping.

    Usage:
        moments = SteelSeriesMoments()
        moments.register()  # Call once at startup
        moments.clip()      # Call to save a clip
    """

    GAME_NAME = "REX"
    GAME_DISPLAY_NAME = "REX Voice Assistant"
    CLIP_RULE_KEY = "voice_clip"

    def __init__(self, timeout: int = 5):
        self.timeout = timeout
        self._base_url: Optional[str] = None
        self._registered = False

    def _get_base_url(self) -> Optional[str]:
        """Get or discover the GameSense server URL."""
        if self._base_url is None:
            address = _get_gamesense_address()
            if address:
                self._base_url = f"http://{address}"
                logger.debug("SteelSeries GameSense server: %s", self._base_url)
            else:
                logger.warning("SteelSeries GG not found. Is it running?")
        return self._base_url

    def _post(self, endpoint: str, data: dict) -> bool:
        """POST to GameSense endpoint. Returns True on success."""
        base = self._get_base_url()
        if not base:
            return False

        requests = _get_requests()
        try:
            r = requests.post(f"{base}/{endpoint}", json=data, timeout=self.timeout)
            r.raise_for_status()
            logger.debug("SteelSeries %s: %s", endpoint, r.text[:200])
            return True
        except requests.exceptions.Timeout:
            logger.error("SteelSeries %s timed out", endpoint)
            return False
        except requests.exceptions.RequestException as e:
            logger.error("SteelSeries %s failed: %s", endpoint, e)
            return False

    def register(self) -> bool:
        """
        Register REX with GameSense and set up autoclip rules.

        Call this once at startup. Safe to call multiple times.
        """
        if self._registered:
            return True

        # Register game metadata
        metadata = {
            "game": self.GAME_NAME,
            "game_display_name": self.GAME_DISPLAY_NAME,
            "developer": "REX",
        }
        if not self._post("game_metadata", metadata):
            return False

        # Register autoclip rule
        rules = {
            "game": self.GAME_NAME,
            "rules": [
                {
                    "rule_key": self.CLIP_RULE_KEY,
                    "label": "Voice Command Clip",
                    "default_enabled": True,
                }
            ]
        }
        if not self._post("register_autoclip_rules", rules):
            return False

        self._registered = True
        logger.info("SteelSeries Moments: REX registered for clipping")
        return True

    def clip(self) -> bool:
        """
        Trigger a clip save in SteelSeries Moments.

        Returns True if the request succeeded (clip may still fail if
        Moments isn't recording or autoclipping is disabled for REX).
        """
        # Auto-register if needed
        if not self._registered:
            self.register()

        trigger = {
            "game": self.GAME_NAME,
            "key": self.CLIP_RULE_KEY,
        }

        success = self._post("autoclip", trigger)
        if success:
            logger.info("SteelSeries Moments: Clip triggered")
        return success


# Module-level singleton
_moments: Optional[SteelSeriesMoments] = None


def _get_moments() -> SteelSeriesMoments:
    """Get or create the Moments singleton."""
    global _moments
    if _moments is None:
        _moments = SteelSeriesMoments()
    return _moments


# Public command functions (called by matcher.py)
def clip_that() -> None:
    """Trigger a clip save via SteelSeries Moments."""
    _get_moments().clip()

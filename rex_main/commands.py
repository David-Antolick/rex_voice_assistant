# commands.py  – v2 (https://github.com/ytmdesktop/ytmdesktop/wiki/v2-%E2%80%90-Companion-Server-API-v1)
from __future__ import annotations
import os, requests
from typing import Any, Optional
from dotenv import load_dotenv
from ytmusicapi import YTMusic

import logging
logger = logging.getLogger(__name__)
load_dotenv()        # take environment variables from .env.

'''Confusingly, YTMD app currently interfaces as the v2 api, but has v1 in the URL.'''

__all__ = [
    "ytmd", "play_music", "stop_music", "next_track", "previous_track",
    "restart_track", "volume_up", "volume_down", "set_volume",
    "like", "dislike",
]

class YTMD:
    """Thin client for YT Music Desktop Companion-Server (POST /api/v1/command)."""

    def __init__(
        self,
        host: str | None = None,
        port: str | None = None,
        token: str | None = None,
        timeout: int = 5,
    ) -> None:
        self.host   = host   or os.getenv("YTMD_HOST",  "host.docker.internal")
        self.port   = port   or os.getenv("YTMD_PORT",  "9863")
        self.token  = token  or os.getenv("YTMD_TOKEN")
        self.timeout = timeout

        self._base_url = f"http://{self.host}:{self.port}/api/v1/command"
        self._headers  = {"Content-Type": "application/json"}
        if self.token:                       # include only if present
            self._headers["Authorization"] = self.token


    #  low-level helper
    def _send(self, command: str, *, value: Optional[Any] = None) -> None:
        payload: dict[str, Any] = {"command": command}
        if value is not None:
            payload["data"] = value

        try:
            r = requests.post(
                self._base_url,
                json=payload,
                headers=self._headers,
                timeout=self.timeout,
            )
            r.raise_for_status()
        except requests.exceptions.Timeout as e:
            logger.error("YTMD command %r timed out after %ss", command, self.timeout)
            raise
        except requests.exceptions.HTTPError as e:
            # e.response.status_code is available if you need it
            status = e.response.status_code if e.response else "??"
            logger.error("YTMD command %r failed: HTTP %s", command, status)
            raise
        except requests.exceptions.RequestException as e:
            logger.error("YTMD command %r connection error: %s", command, e)
            raise
        else:
            logger.debug("YTMD → %s (%s)", command, value)



    def play_song(self, title: str, artist: str | None = None) -> None:
        """
        Search YouTube Music (actual) for “title [+ artist]” and play the first match.
        """
        # 1) Build and run the search
        query = f"{title} by {artist}" if artist else title
        from ytmusicapi import YTMusic
        ytm = YTMusic()
        results = ytm.search(query, filter="songs", limit=1)

        if not results:
            logger.error("No YTM results for %r", query)
            return

        # 2) Pull out the videoId
        video_id = results[0].get("videoId")
        if not video_id:
            logger.error("Search hit with no videoId: %r", results[0])
            return

        # 3) Hit the Companion-Server
        #    You need {"command":"changeVideo","data":{…}}
        self._send("changeVideo",
                   value={"videoId": video_id, "playlistId": None})
        logger.info("YTMD playing videoId %s", video_id)


    #  music control
    def play_music(self):
        self._send("play")

    def stop_music(self):
        self._send("pause")

    def next_track(self):
        self._send("next")

    def previous_track(self):
        self._send("seekTo", value=4) # skips to 4 seconds (threshold for previous)
        self._send("previous")

    def restart_track(self):
        self._send("seekTo", value=5)  # skips to 5 seconds (threshold for restart)
        self._send("previous")


    # volume 
    def volume_up(self):
        self._send("volumeUp")
    def volume_down(self):
        self._send("volumeDown")

    def set_volume(self, level: int | str) -> None:
        try:
            vol = max(0, min(100, int(level)))
        except (ValueError, TypeError):
            logger.error("Bad volume value: %s", level)
            return
        self._send("setVolume", value=vol)


    # thumbs
    def like(self):
        self._send("toggleLike")
    def dislike(self):
        self._send("toggleDislike")

    # memes
    def so_sad(self):
        """Send a 'so sad' command to YTMD."""
        self._send("changeVideo",
                   value={"videoId": 'FdMG84qN_98', "playlistId": None})
        logger.info("YTMD playing videoId %s", 'FdMG84qN_98')


# singleton + shims
ytmd = YTMD()

play_music     = ytmd.play_music
stop_music     = ytmd.stop_music
next_track     = ytmd.next_track
previous_track = ytmd.previous_track
restart_track  = ytmd.restart_track
play_song      = ytmd.play_song

volume_up      = ytmd.volume_up
volume_down    = ytmd.volume_down
set_volume     = ytmd.set_volume

like           = ytmd.like
dislike        = ytmd.dislike
so_sad         = ytmd.so_sad

"""
Command handlers for REX that control YouTube-Music-Desktop-App
via its Companion-Server (https://github.com/ytmdesktop/ytmdesktop)
"""

import logging
import requests
import os
from dotenv import load_dotenv


load_dotenv()  # reads .env into os.environ

YTMD_TOKEN = os.getenv("YTMD_TOKEN")
YTMD_HOST  = os.getenv("YTMD_HOST", "host.docker.internal")
YTMD_PORT  = os.getenv("YTMD_PORT", "9863")

ENDPOINT = f"http://{YTMD_HOST}:{YTMD_PORT}/api/v1/command"




_TIMEOUT = 2.0  # seconds


def _send(cmd: str, value: str | None = None):
    """
    POST a command to YTMDesktop’s Companion Server.
    Safe-fails with a log entry on error.
    """
    headers = {"Authorization": YTMD_TOKEN}
    payload = {"command": cmd}
    if value is not None:
        payload["value"] = value

    try:
        r = requests.post(
            ENDPOINT,
            json=payload,
            headers=headers,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        logging.info("YTMD ➜ %s(%s) OK", cmd, value)
    except Exception as exc:
        logging.error("YTMD command %s failed: %s", cmd, exc)



def start_music():
    _send("play")

def stop_music():
    _send("pause")

def next_track():
    _send("next")

def previous_track():
    _send("previous")

def volume_up():
    _send("volumeup")

def volume_down():
    _send("volumedown")

def play_song(title: str, artist: str | None = None):
    # Search/queue requires Companion-Server v2; stub for now.
    logging.info("TODO play_song('%s', '%s')", title, artist)

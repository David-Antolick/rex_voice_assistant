# stand_app/commands.py
"""
Stubbed command handlers for matched voice commands.
Each function should eventually perform real system actions (e.g., media control).
For now, they just print what would happen.
"""

def stop_music():
    print("[EXEC] stop_music() → Stopping playback")


def start_music():
    print("[EXEC] start_music() → Starting playback")


def play_song(title: str, artist: str | None = None):
    if artist:
        print(f"[EXEC] play_song() → Playing '{title}' by {artist}")
    else:
        print(f"[EXEC] play_song() → Playing '{title}'")

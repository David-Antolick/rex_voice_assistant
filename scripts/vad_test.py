# scripts/vad_test.py
import os
os.environ["TORCH_CPP_LOG_LEVEL"] = "ERROR"

from app.audio.recorder import AudioChunk
from app.audio.vad import is_speech
from scripts.wav_feed_test import wav_stream



for chunk in wav_stream("sounds/basic_commands.wav"):
    tag = "1" if is_speech(chunk) else "0"
    print(f"{chunk.t0:>5.2f}s {tag}")

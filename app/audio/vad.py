# app/audio/vad.py
# Silero VAD via torch.hub
import os
os.environ["TORCH_CPP_LOG_LEVEL"] = "ERROR"

import torch, numpy as np
from app.audio.recorder import AudioChunk


# Load once (will cache the JIT model)
model, utils = torch.hub.load(
    repo_or_dir='snakers4/silero-vad',
    model='silero_vad',
    force_reload=False
)
get_speech_timestamps, _, _, _, _ = utils

def is_speech(chunk: AudioChunk, threshold: float = 0.6) -> bool:
    """
    Return True if `chunk` contains speech.
    We normalize int16 PCM → float32 in [-1,1], then ask Silero for any voice timestamps.
    """
    # 1) Normalize
    audio = chunk.pcm.astype(np.float32) / 32768.0
    # 2) Get speech segments (list of {start, end})
    speech = get_speech_timestamps(
        audio,
        model,
        sampling_rate=16_000,
        threshold=threshold,
        return_seconds=True
    )
    return len(speech) > 0

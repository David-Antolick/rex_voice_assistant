"""vad_stream.py
Streaming Voice-Activity Detection using Silero-VAD.

The coroutine `SileroVAD.run()` listens on *in_queue* (20-ms PCM frames)
and groups them into utterances.  When an utterance ends (>=300 ms of
silence) the concatenated NumPy array is pushed to *out_queue*.

This module is intentionally stateless between runs so you can unit-test
or hot-swap parameters.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import torch

__all__ = ["SileroVAD"]

_REPO = "snakers4/silero-vad"
_MODEL = "silero_vad"


class SileroVAD:
    """Stream wrapper around Silero voice-activity detector.

    Parameters
    ----------
    in_queue : asyncio.Queue[np.ndarray]
        Queue that delivers fixed-length float32 PCM frames (shape (N,)).
    out_queue : asyncio.Queue[np.ndarray]
        Destination queue that will receive full-utterance arrays.
    sample_rate : int, default 16_000
        Must match the rate used by *audio_stream.py* and Whisper.
    frame_ms : int, default 40
        Duration of each frame (needed for silence timeout math).
    speech_threshold : float, default 0.5
        Probability from the model above which a frame is considered speech.
    silence_ms : int, default 300
        Emit an utterance after this much trailing silence.
    max_utterance_ms : int, default 10_000
        Hard cut-off (to avoid runaway buffers if silence never detected).
    """

    def __init__(
        self,
        in_queue: asyncio.Queue,
        out_queue: asyncio.Queue,
        *,
        sample_rate: int = 16_000,
        frame_ms: int = 32,
        speech_threshold: float = 0.65,
        silence_ms: int = 500,
        max_utterance_ms: int = 10_000,
    ):
        self.in_q = in_queue
        self.out_q = out_queue
        self.sr = sample_rate
        self.frame_ms = frame_ms
        self.speech_th = speech_threshold
        self.silence_frames = silence_ms // frame_ms
        self.max_frames = max_utterance_ms // frame_ms

        # Lazily-loaded Torch model (so `torch.hub` runs only inside the first loop)
        self._model: Optional[torch.jit.ScriptModule] = None
        self._h: Optional[Tuple[torch.Tensor, torch.Tensor]] = None  # LSTM hidden-state

    async def run(self):  # noqa: C901 – a bit long but readable
        """Endless coroutine – call with `asyncio.create_task`."""
        self._lazy_init()
        speech_buf: list[np.ndarray] = []
        silence_ctr = 0

        while True:
            frame = await self.in_q.get()
            speech_prob = self._infer(frame)

            if speech_prob >= self.speech_th:
                speech_buf.append(frame)
                silence_ctr = 0
            else:
                if speech_buf:
                    silence_ctr += 1

                    if silence_ctr >= self.silence_frames or len(speech_buf) >= self.max_frames:
                        # Flush utterance
                        utterance = np.concatenate(speech_buf, dtype=np.float32)
                        await self.out_q.put(utterance)
                        speech_buf.clear()
                        silence_ctr = 0

            # clean up queue task tracking (optional but polite)
            self.in_q.task_done()

    def _lazy_init(self):
        if self._model is not None:
            return

        # load TorchScript model + utility fns
        self._model, utils = torch.hub.load(_REPO, _MODEL, trust_repo=True)
        self._model.eval().to("cpu")          # tiny → CPU is fine
        # utils[0] is now get_speech_timestamps()  – we DON'T need it here
        # because we want frame-wise scores. We'll query the model directly.

    def _infer(self, pcm: np.ndarray) -> float:
        """Return speech probability for one ~40 ms frame."""
        with torch.no_grad():
            wav = torch.from_numpy(pcm).unsqueeze(0)        # shape (1, N)
            logits = self._model(wav, self.sr)              # (T, 1) or (T, 2)

            # pick the last frame, column 0 (speech logit)
            speech_logit = logits[-1, 0]
            speech_prob = float(torch.sigmoid(logits[-1, 0]))
            print(f"VAD={speech_prob:.2f}")
            return float(torch.sigmoid(speech_logit).item())

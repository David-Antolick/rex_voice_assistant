"""vad_stream.py
Streaming Voice-Activity Detection using Silero-VAD.

The coroutine `SileroVAD.run()` listens on *in_queue* (32-ms PCM frames)
and groups them into utterances.  When an utterance ends (>=300 ms of
silence) the concatenated NumPy array is pushed to *out_queue*.

This module is intentionally stateless between runs so you can unit-test
or hot-swap parameters.
"""

from __future__ import annotations

import asyncio
from typing import Optional, Tuple
from collections import deque
import numpy as np
import torch
import logging

from rex_main.metrics import metrics
from rex_main.benchmark import benchmark

logger = logging.getLogger(__name__)


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
    silence_ms : int, default 400
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
        silence_ms: int = 400,
        max_utterance_ms: int = 10_000,
        pre_speech_ms: int = 100
    ):
        self.in_q = in_queue
        self.out_q = out_queue
        self.sr = sample_rate
        self.frame_ms = frame_ms
        self.speech_th = speech_threshold
        self.silence_frames = silence_ms // frame_ms
        self.max_frames = max_utterance_ms // frame_ms
        self.pre_speech_frames = pre_speech_ms // frame_ms
        self._pre_buf = deque(maxlen=self.pre_speech_frames)


        # Show VAD params
        logger.debug(
            "SileroVAD init: sr=%d, frame_ms=%d, speech_th=%.2f, "
            "silence_frames=%d, max_frames=%d",
            self.sr, self.frame_ms, self.speech_th,
            self.silence_frames, self.max_frames,
        )

        # Lazily-loaded Torch model
        self._model: Optional[torch.jit.ScriptModule] = None
        self._h: Optional[Tuple[torch.Tensor, torch.Tensor]] = None  # LSTM hidden-state

    async def run(self):  # noqa: C901
        """Endless coroutine - call with `asyncio.create_task`."""
        self._lazy_init()
        speech_buf: list[np.ndarray] = []
        silence_ctr = 0

        while True:
            frame = await self.in_q.get()

            if not speech_buf:
                self._pre_buf.append(frame)

            speech_prob = self._infer(frame)

            if speech_prob >= self.speech_th:
                if not speech_buf:
                    # first real speech frame - prepend the buffer
                    speech_buf.extend(self._pre_buf)
                    self._pre_buf.clear()
                    # Record speech start for metrics
                    metrics.record_speech_start()
                    benchmark.record_speech_start()
                speech_buf.append(frame)
                silence_ctr = 0
            else:
                if speech_buf:
                    silence_ctr += 1

                    if silence_ctr >= self.silence_frames or len(speech_buf) >= self.max_frames:
                        # Flush utterance
                        utterance = np.concatenate(speech_buf, dtype=np.float32)
                        frame_count = len(speech_buf)
                        duration_s = frame_count * (self.frame_ms / 1000)
                        duration_ms = duration_s * 1000
                        logger.info(
                            "SileroVAD flushing utterance: %d frames (~%.2f s)",
                            frame_count, duration_s
                        )
                        # Record VAD emit for metrics
                        metrics.record_vad_emit(duration_ms)
                        benchmark.record_vad_complete(duration_ms, duration_ms)
                        await self.out_q.put(utterance)
                        speech_buf.clear()
                        self._pre_buf.clear()
                        silence_ctr = 0

            # clean up queue task tracking
            self.in_q.task_done()

    def _lazy_init(self):
        if self._model is not None:
            return

        # load TorchScript model + utility fns
        self._model, utils = torch.hub.load(_REPO, _MODEL, trust_repo=True)
        self._model.eval().to("cpu")          # tiny, so cpu is fine


    def _infer(self, pcm: np.ndarray) -> float:
        """Return speech probability for one 32 ms frame."""
        with torch.no_grad():
            wav = torch.from_numpy(pcm).unsqueeze(0)        # shape (1, N)
            logits = self._model(wav, self.sr)

            # pick the last frame, column 0 (speech logit)
            speech_logit = logits[-1, 0]
            return float(torch.sigmoid(speech_logit).item())

"""whisper_worker.py
Streaming ASR worker built on *faster-whisper* (CTranslate2 backend).

Consumes full-utterance PCM arrays from *in_queue* and puts the
recognised text (str) onto *out_queue* as soon as decoding completes.
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

import numpy as np
from faster_whisper import WhisperModel, utils as fw_utils  # type: ignore

__all__ = ["WhisperWorker"]


class WhisperWorker:
    """Wrapper around *faster-whisper* for non-blocking transcription.

    Parameters
    ----------
    in_queue : asyncio.Queue[np.ndarray]
        Utterance-level PCM (float32, −1…1, 16 kHz).
    out_queue : asyncio.Queue[str]
        Recognised text; lower-cased, stripped.
    model_name : str, default "small.en"
        Same names as OpenAI/Whisper (tiny | base | small | medium | large).
    device : str, default "cuda" if available else "cpu"
    compute_type : {"float16", "int8"}, default "float16"
        Mixed-precision mode.  "float16" needs a GPU with FP16 support.
    beam_size : int, default 1
        Higher → better accuracy, slower latency.
    """

    def __init__(
        self,
        in_queue: asyncio.Queue,
        out_queue: asyncio.Queue,
        *,
        model_name: str = "small.en",
        device: Optional[str] = None,
        compute_type: str = "float16",
        beam_size: int = 1,
    ):
        self.in_q = in_queue
        self.out_q = out_queue
        self.model_name = model_name
        self.device = device or ("cuda" if fw_utils.has_cuda() else "cpu")
        self.compute_type = compute_type if self.device == "cuda" else "float32"
        self.beam_size = beam_size

        # model will be loaded lazily inside the first loop iteration so that
        # unit tests can monkey-patch environment variables before import.
        self._model: Optional[WhisperModel] = None

    async def run(self):
        """Endless worker coroutine."""
        self._lazy_init()
        assert self._model is not None

        while True:
            pcm = await self.in_q.get()
            text = await asyncio.get_running_loop().run_in_executor(
                None, self._transcribe, pcm
            )
            await self.out_q.put(text)
            self.in_q.task_done()

    def _lazy_init(self):
        if self._model is not None:
            return

        # Allow HF cache overwrite for container images with read-only home
        os.environ.setdefault("HF_HUB_CACHE", "/tmp/hf_cache")

        self._model = WhisperModel(
        self.model_name,
        device=self.device,
        compute_type=self.compute_type,
        download_root=os.getenv("HF_MODEL_HOME", "/tmp/hf_models"),
        )   

    # called in threadpool so can be blocking/heavy
    def _transcribe(self, pcm: np.ndarray) -> str:
        assert self._model is not None

        segments, _info = self._model.transcribe(
            pcm,
            beam_size=self.beam_size,
            temperature=0.0,
            best_of=1,
            vad_filter=False,  # we already did VAD
            language="en",
        )
        # 'segments' is a generator; join on the fly
        return " ".join(seg.text.strip() for seg in segments).lower().strip()

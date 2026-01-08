"""whisper_worker.py
Streaming ASR worker built on *faster-whisper* (CTranslate2 backend).

Consumes full-utterance PCM arrays from *in_queue* and puts the
recognised text (str) onto *out_queue* as soon as decoding completes.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Optional

import numpy as np
import time

import logging

from rex_main.metrics import metrics
from rex_main.benchmark import benchmark

logger = logging.getLogger(__name__)
logging.getLogger("faster_whisper").setLevel(logging.WARNING)


def _setup_cuda_paths():
    """Add NVIDIA CUDA DLLs to PATH on Windows.

    The nvidia-cudnn-cu12 and nvidia-cublas-cu12 packages install DLLs
    but they're not automatically in the DLL search path. This adds them
    so CTranslate2 can find cudnn_ops64_9.dll, cublas64_12.dll, etc.
    """
    if sys.platform != "win32":
        return

    paths_to_add = []

    # cuDNN DLLs
    try:
        import nvidia.cudnn
        cudnn_bin = os.path.join(os.path.dirname(nvidia.cudnn.__file__), "bin")
        if os.path.isdir(cudnn_bin):
            paths_to_add.append(cudnn_bin)
    except ImportError:
        logger.debug("nvidia-cudnn-cu12 not installed")
    except Exception as e:
        logger.debug("Could not find cuDNN path: %s", e)

    # cuBLAS DLLs
    try:
        import nvidia.cublas
        cublas_bin = os.path.join(os.path.dirname(nvidia.cublas.__file__), "bin")
        if os.path.isdir(cublas_bin):
            paths_to_add.append(cublas_bin)
    except ImportError:
        logger.debug("nvidia-cublas-cu12 not installed")
    except Exception as e:
        logger.debug("Could not find cuBLAS path: %s", e)

    # Add all paths
    if paths_to_add:
        for p in paths_to_add:
            current_path = os.environ.get("PATH", "")
            if p not in current_path:
                os.environ["PATH"] = p + os.pathsep + current_path
                logger.debug("Added to PATH: %s", p)
                if hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(p)


__all__ = ["WhisperWorker"]


class WhisperWorker:
    """Wrapper around *faster-whisper* for non-blocking transcription.

    Parameters
    ----------
    in_queue : asyncio.Queue[np.ndarray]
        Utterance-level PCM (float32, -1…1, 16 kHz).
    out_queue : asyncio.Queue[str]
        Recognised text; lower-cased, stripped.
    model_name : str, default "small.en"
        Same names as OpenAI/Whisper (tiny | base | small | medium | large).
    device : str, default "cuda" if available else "cpu"
    compute_type : {"float16", "int8"}, default "float16"
        Mixed-precision mode.  "float16" needs a GPU with FP16 support.
    beam_size : int, default 1
        Higher = better accuracy, slower latency.
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

        # Handle device selection:
        # - "auto" or None: auto-detect CUDA, fall back to CPU
        # - "cuda": use CUDA (will fail if not available)
        # - "cpu": use CPU
        if device in (None, "auto"):
            self.device = self._detect_device()
        else:
            self.device = device

        self.compute_type = compute_type if self.device == "cuda" else "float32"
        self.beam_size = beam_size

        logger.debug(
            "WhisperWorker init: model=%s, device=%s, compute_type=%s, beam=%d",
            self.model_name, self.device, self.compute_type, self.beam_size,
        )

        # model will be loaded lazily inside the first loop iteration so that
        self._model = None  # WhisperModel, imported lazily

    def _detect_device(self) -> str:
        """Auto-detect best available device (CUDA if available, else CPU)."""
        try:
            import torch
            if torch.cuda.is_available():
                logger.info("CUDA detected, using GPU acceleration")
                return "cuda"
        except ImportError:
            pass
        except Exception as e:
            logger.debug("CUDA detection failed: %s", e)

        logger.info("CUDA not available, using CPU")
        return "cpu"

    async def run(self):
        """Endless worker coroutine."""
        self._lazy_init()
        assert self._model is not None

        while True:
            pcm = await self.in_q.get()

            # Debug: chunk size & duration
            cnt = pcm.shape[0] if hasattr(pcm, "shape") else len(pcm)
            dur = cnt / 16000
            logger.debug("WhisperWorker got %d samples (~%.2f s)", cnt, dur)

            # Debug: transcription timing
            t0 = time.perf_counter()
            text = await asyncio.get_running_loop().run_in_executor(
                None, self._transcribe, pcm
            )
            dt = (time.perf_counter() - t0) * 1000
            logger.debug("WhisperWorker transcription took %.1f ms", dt)

            # Record transcription for metrics
            metrics.record_transcription(text, dt)
            benchmark.record_transcription(dt)

            # Debug: transcription output
            logger.debug("WhisperWorker text: %r", text)

            await self.out_q.put(text)
            self.in_q.task_done()

    def _lazy_init(self):
        if self._model is not None:
            return

        # Allow HF cache overwrite for container images with read-only home
        os.environ.setdefault("HF_HUB_CACHE", "/tmp/hf_cache")

        # Setup CUDA DLL paths on Windows before loading CUDA model
        if self.device == "cuda":
            _setup_cuda_paths()

        # Import WhisperModel here AFTER setting up CUDA paths
        # This ensures ctranslate2 can find the CUDA DLLs
        from faster_whisper import WhisperModel

        # Try to load on requested device, fall back to CPU if CUDA fails
        device = self.device
        compute_type = self.compute_type

        try:
            self._model = WhisperModel(
                self.model_name,
                device=device,
                compute_type=compute_type,
                download_root=os.getenv("HF_MODEL_HOME", "/tmp/hf_models"),
            )
            # Test transcription to catch cuDNN errors that only appear at inference time
            if device == "cuda":
                self._test_inference()
        except Exception as e:
            if device == "cuda":
                logger.warning("CUDA initialization failed: %s", e)
                logger.warning("Falling back to CPU mode")
                device = "cpu"
                compute_type = "float32"
                self._model = WhisperModel(
                    self.model_name,
                    device=device,
                    compute_type=compute_type,
                    download_root=os.getenv("HF_MODEL_HOME", "/tmp/hf_models"),
                )
            else:
                raise

        # Update instance vars to reflect actual device used
        self.device = device
        self.compute_type = compute_type

        logger.info(
            "Loaded WhisperModel '%s' on %s [%s]",
            self.model_name, self.device, self.compute_type,
        )

    def _test_inference(self):
        """Run a tiny test transcription to verify CUDA/cuDNN actually works."""
        # Generate 0.1 seconds of silence for a quick test
        test_audio = np.zeros(1600, dtype=np.float32)
        # This will throw if cuDNN is broken
        segments, _ = self._model.transcribe(
            test_audio,
            beam_size=1,
            language="en",
        )
        # Force generator to execute
        list(segments)

    def warmup(self) -> float:
        """Pre-warm the model by running a test transcription.

        Call this before the main loop to eliminate cold-start latency.

        Returns:
            float: Warmup time in milliseconds
        """
        self._lazy_init()
        assert self._model is not None

        # Generate 0.5 seconds of silence for warmup
        # This is enough to fully warm up the model's inference path
        warmup_audio = np.zeros(8000, dtype=np.float32)

        logger.info("Warming up Whisper model...")
        t0 = time.perf_counter()

        segments, _ = self._model.transcribe(
            warmup_audio,
            beam_size=self.beam_size,
            temperature=0.0,
            language="en",
        )
        # Force generator execution
        list(segments)

        warmup_ms = (time.perf_counter() - t0) * 1000
        logger.info("Whisper warmup completed in %.0f ms", warmup_ms)
        return warmup_ms

    # called in threadpool so can be blocking/heavy
    def _transcribe(self, pcm: np.ndarray) -> str:
        assert self._model is not None

        segments, _info = self._model.transcribe(
            pcm,
            beam_size=self.beam_size,
            temperature=0.0,
            best_of=1,
            vad_filter=False,  # seperate VAD
            language="en",
        )
        # 'segments' is a generator; join on the fly
        return " ".join(seg.text.strip() for seg in segments).lower().strip()

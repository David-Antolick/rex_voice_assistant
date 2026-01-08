"""benchmark.py
Comprehensive benchmarking and resource monitoring for REX Voice Assistant.

Tracks:
- Per-command latency with full pipeline breakdown
- CPU usage (per-core and overall)
- GPU usage and memory (if NVIDIA GPU available)
- System memory usage
- Historical data with persistence for version comparison

Usage:
    from rex_main.benchmark import benchmark

    # Record a command execution
    benchmark.record_command("next_track", e2e_ms=850, vad_ms=300, whisper_ms=200, execute_ms=5)

    # Get current system stats
    stats = benchmark.get_system_stats()

    # Export session data for comparison
    benchmark.export_session("session_v0.2.0.json")
"""

from __future__ import annotations

import json
import platform
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any
import logging

logger = logging.getLogger(__name__)

__all__ = ["benchmark", "BenchmarkCollector", "CommandRecord", "SystemSnapshot"]


@dataclass
class CommandRecord:
    """Record of a single command execution with full timing breakdown."""
    timestamp: str
    command: str
    text: str
    matched: bool

    # Timing breakdown (all in ms)
    e2e_ms: float  # End-to-end from speech start to command complete
    vad_ms: float  # Time in VAD (speech duration + silence timeout)
    whisper_ms: float  # Transcription time
    execute_ms: float  # Command execution time

    # Additional metadata
    audio_duration_ms: float = 0.0  # Actual audio length
    early_match: bool = False  # Was this an early match (FastVAD)?
    model: str = ""
    mode: str = "standard"  # "standard" or "low-latency"


@dataclass
class SystemSnapshot:
    """Snapshot of system resource usage."""
    timestamp: str

    # CPU
    cpu_percent: float  # Overall CPU usage
    cpu_per_core: List[float] = field(default_factory=list)

    # Memory
    memory_percent: float = 0.0
    memory_used_mb: float = 0.0
    memory_available_mb: float = 0.0

    # GPU (NVIDIA only)
    gpu_available: bool = False
    gpu_name: str = ""
    gpu_percent: float = 0.0
    gpu_memory_used_mb: float = 0.0
    gpu_memory_total_mb: float = 0.0
    gpu_temperature: float = 0.0


@dataclass
class SessionSummary:
    """Summary statistics for a session."""
    version: str
    start_time: str
    end_time: str
    mode: str
    model: str

    # Command stats
    total_commands: int
    matched_commands: int
    match_rate: float

    # Latency stats (ms)
    avg_e2e_ms: float
    min_e2e_ms: float
    max_e2e_ms: float
    p50_e2e_ms: float
    p95_e2e_ms: float

    avg_vad_ms: float
    avg_whisper_ms: float
    avg_execute_ms: float

    # Resource stats (averages)
    avg_cpu_percent: float
    avg_memory_percent: float
    avg_gpu_percent: float
    avg_gpu_memory_mb: float


class BenchmarkCollector:
    """Collects and manages benchmark data with persistence."""

    def __init__(self, data_dir: Optional[Path] = None, max_commands: int = 10000):
        self._lock = threading.RLock()

        # Data directory for persistence
        if data_dir is None:
            data_dir = Path.home() / ".rex" / "benchmarks"
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Session info
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.start_time = datetime.now()
        self.version = self._get_version()
        self.mode = "standard"
        self.model = "unknown"

        # Command records
        self._commands: deque[CommandRecord] = deque(maxlen=max_commands)

        # System snapshots (taken periodically)
        self._snapshots: deque[SystemSnapshot] = deque(maxlen=1000)

        # Current pipeline state for E2E calculation
        self._current_speech_start: Optional[float] = None
        self._current_vad_ms: float = 0.0
        self._current_whisper_ms: float = 0.0
        self._current_audio_duration_ms: float = 0.0

        # Resource monitoring
        self._psutil_available = False
        self._pynvml_available = False
        self._init_resource_monitors()

        # Start background resource monitoring
        self._stop_monitoring = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None

    def _get_version(self) -> str:
        """Get REX version from pyproject.toml or fallback."""
        try:
            import importlib.metadata
            return importlib.metadata.version("rex-voice-assistant")
        except Exception:
            try:
                pyproject = Path(__file__).parent.parent / "pyproject.toml"
                if pyproject.exists():
                    content = pyproject.read_text()
                    for line in content.split("\n"):
                        if line.startswith("version"):
                            return line.split("=")[1].strip().strip('"')
            except Exception:
                pass
        return "unknown"

    def _init_resource_monitors(self):
        """Initialize resource monitoring libraries (silent if not available)."""
        try:
            import psutil
            self._psutil_available = True
            self._psutil = psutil
        except ImportError:
            # Silently disable - user can install psutil if they want resource monitoring
            pass

        try:
            import pynvml
            pynvml.nvmlInit()
            self._pynvml_available = True
            self._pynvml = pynvml

            # Get GPU info
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self._gpu_name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(self._gpu_name, bytes):
                self._gpu_name = self._gpu_name.decode()
            self._gpu_handle = handle
        except ImportError:
            pass  # Silently disable
        except Exception:
            pass  # GPU not available or init failed

    def start_monitoring(self, interval_seconds: float = 1.0):
        """Start background resource monitoring."""
        if self._monitor_thread is not None:
            return

        self._stop_monitoring.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval_seconds,),
            daemon=True,
            name="rex-benchmark-monitor"
        )
        self._monitor_thread.start()
        logger.info("Benchmark monitoring started (interval: %.1fs)", interval_seconds)

    def stop_monitoring(self):
        """Stop background resource monitoring."""
        if self._monitor_thread is None:
            return
        self._stop_monitoring.set()
        self._monitor_thread.join(timeout=2.0)
        self._monitor_thread = None
        logger.info("Benchmark monitoring stopped")

    def _monitor_loop(self, interval: float):
        """Background loop for resource monitoring."""
        while not self._stop_monitoring.is_set():
            try:
                snapshot = self.get_system_stats()
                with self._lock:
                    self._snapshots.append(snapshot)
            except Exception as e:
                logger.debug("Error collecting system stats: %s", e)

            self._stop_monitoring.wait(interval)

    def set_session_info(self, mode: str, model: str):
        """Set session metadata."""
        with self._lock:
            self.mode = mode
            self.model = model

    # --- Pipeline timing methods ---

    def record_speech_start(self):
        """Record when speech starts (for E2E calculation)."""
        with self._lock:
            self._current_speech_start = time.perf_counter()
            self._current_vad_ms = 0.0
            self._current_whisper_ms = 0.0
            self._current_audio_duration_ms = 0.0

    def record_vad_complete(self, duration_ms: float, audio_duration_ms: float = 0.0):
        """Record VAD completion."""
        with self._lock:
            self._current_vad_ms = duration_ms
            self._current_audio_duration_ms = audio_duration_ms

    def record_transcription(self, latency_ms: float):
        """Record transcription completion."""
        with self._lock:
            self._current_whisper_ms = latency_ms

    def record_command(
        self,
        command: str,
        text: str,
        matched: bool,
        execute_ms: float = 0.0,
        early_match: bool = False,
    ):
        """Record a complete command execution with full timing."""
        with self._lock:
            # Calculate E2E
            e2e_ms = 0.0
            if self._current_speech_start is not None:
                e2e_ms = (time.perf_counter() - self._current_speech_start) * 1000

            record = CommandRecord(
                timestamp=datetime.now().isoformat(),
                command=command or "none",
                text=text,
                matched=matched,
                e2e_ms=e2e_ms,
                vad_ms=self._current_vad_ms,
                whisper_ms=self._current_whisper_ms,
                execute_ms=execute_ms,
                audio_duration_ms=self._current_audio_duration_ms,
                early_match=early_match,
                model=self.model,
                mode=self.mode,
            )
            self._commands.append(record)

            # Log for visibility
            if matched:
                logger.info(
                    "BENCHMARK: %s | E2E: %.0fms | VAD: %.0fms | Whisper: %.0fms | Exec: %.0fms%s",
                    command, e2e_ms, self._current_vad_ms, self._current_whisper_ms,
                    execute_ms, " [EARLY]" if early_match else ""
                )

            # Reset for next command
            self._current_speech_start = None

    # --- Query methods ---

    def get_system_stats(self) -> SystemSnapshot:
        """Get current system resource usage."""
        snapshot = SystemSnapshot(
            timestamp=datetime.now().isoformat(),
            cpu_percent=0.0,
        )

        if self._psutil_available:
            try:
                snapshot.cpu_percent = self._psutil.cpu_percent(interval=None)
                snapshot.cpu_per_core = self._psutil.cpu_percent(percpu=True)

                mem = self._psutil.virtual_memory()
                snapshot.memory_percent = mem.percent
                snapshot.memory_used_mb = mem.used / (1024 * 1024)
                snapshot.memory_available_mb = mem.available / (1024 * 1024)
            except Exception as e:
                logger.debug("Error getting CPU/memory stats: %s", e)

        if self._pynvml_available:
            try:
                snapshot.gpu_available = True
                snapshot.gpu_name = self._gpu_name

                util = self._pynvml.nvmlDeviceGetUtilizationRates(self._gpu_handle)
                snapshot.gpu_percent = util.gpu

                mem = self._pynvml.nvmlDeviceGetMemoryInfo(self._gpu_handle)
                snapshot.gpu_memory_used_mb = mem.used / (1024 * 1024)
                snapshot.gpu_memory_total_mb = mem.total / (1024 * 1024)

                try:
                    temp = self._pynvml.nvmlDeviceGetTemperature(
                        self._gpu_handle,
                        self._pynvml.NVML_TEMPERATURE_GPU
                    )
                    snapshot.gpu_temperature = temp
                except Exception:
                    pass
            except Exception as e:
                logger.debug("Error getting GPU stats: %s", e)

        return snapshot

    def get_recent_commands(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent command records as dicts."""
        with self._lock:
            commands = list(self._commands)[-limit:]
            return [asdict(c) for c in commands]

    def get_session_summary(self) -> SessionSummary:
        """Get summary statistics for current session."""
        with self._lock:
            commands = list(self._commands)
            snapshots = list(self._snapshots)

        matched = [c for c in commands if c.matched]
        e2e_times = [c.e2e_ms for c in matched if c.e2e_ms > 0]

        # Calculate percentiles
        def percentile(data: List[float], p: float) -> float:
            if not data:
                return 0.0
            sorted_data = sorted(data)
            idx = int(len(sorted_data) * p / 100)
            return sorted_data[min(idx, len(sorted_data) - 1)]

        # Average resource usage
        cpu_values = [s.cpu_percent for s in snapshots if s.cpu_percent > 0]
        mem_values = [s.memory_percent for s in snapshots if s.memory_percent > 0]
        gpu_values = [s.gpu_percent for s in snapshots if s.gpu_available]
        gpu_mem_values = [s.gpu_memory_used_mb for s in snapshots if s.gpu_available]

        return SessionSummary(
            version=self.version,
            start_time=self.start_time.isoformat(),
            end_time=datetime.now().isoformat(),
            mode=self.mode,
            model=self.model,

            total_commands=len(commands),
            matched_commands=len(matched),
            match_rate=len(matched) / len(commands) * 100 if commands else 0,

            avg_e2e_ms=sum(e2e_times) / len(e2e_times) if e2e_times else 0,
            min_e2e_ms=min(e2e_times) if e2e_times else 0,
            max_e2e_ms=max(e2e_times) if e2e_times else 0,
            p50_e2e_ms=percentile(e2e_times, 50),
            p95_e2e_ms=percentile(e2e_times, 95),

            avg_vad_ms=sum(c.vad_ms for c in matched) / len(matched) if matched else 0,
            avg_whisper_ms=sum(c.whisper_ms for c in matched) / len(matched) if matched else 0,
            avg_execute_ms=sum(c.execute_ms for c in matched) / len(matched) if matched else 0,

            avg_cpu_percent=sum(cpu_values) / len(cpu_values) if cpu_values else 0,
            avg_memory_percent=sum(mem_values) / len(mem_values) if mem_values else 0,
            avg_gpu_percent=sum(gpu_values) / len(gpu_values) if gpu_values else 0,
            avg_gpu_memory_mb=sum(gpu_mem_values) / len(gpu_mem_values) if gpu_mem_values else 0,
        )

    def export_session(self, filename: Optional[str] = None) -> Path:
        """Export session data to JSON file for comparison."""
        if filename is None:
            filename = f"session_{self.session_id}_{self.mode}_{self.model}.json"

        filepath = self.data_dir / filename

        with self._lock:
            data = {
                "session_id": self.session_id,
                "summary": asdict(self.get_session_summary()),
                "commands": [asdict(c) for c in self._commands],
                "snapshots": [asdict(s) for s in self._snapshots],
                "system_info": {
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "processor": platform.processor(),
                },
            }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        logger.info("Exported benchmark data to: %s", filepath)
        return filepath

    def compare_sessions(self, session_files: List[Path]) -> Dict[str, Any]:
        """Compare multiple session files and return comparison data."""
        sessions = []

        for filepath in session_files:
            with open(filepath) as f:
                data = json.load(f)
                sessions.append(data["summary"])

        return {
            "sessions": sessions,
            "comparison": {
                "versions": [s["version"] for s in sessions],
                "modes": [s["mode"] for s in sessions],
                "avg_e2e_ms": [s["avg_e2e_ms"] for s in sessions],
                "p95_e2e_ms": [s["p95_e2e_ms"] for s in sessions],
                "avg_cpu_percent": [s["avg_cpu_percent"] for s in sessions],
                "avg_gpu_percent": [s["avg_gpu_percent"] for s in sessions],
            }
        }


# Singleton instance
benchmark = BenchmarkCollector()

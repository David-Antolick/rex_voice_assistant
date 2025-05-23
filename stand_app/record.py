"""
Record from mic and run through your pipeline:
  1) Save to WAV
  2) Preprocess → outputs/processed_audio.npy
  3) VAD → outputs/speech_segments.json
  4) Whisper → outputs/transcript.csv
  5) Match → prints commands
"""
import argparse
import sounddevice as sd
import soundfile as sf
import subprocess
from pathlib import Path

DEFAULT_SR = 16000
DEFAULT_DURATION = 5  # seconds

def record_to_wav(path: Path, duration: float, sr: int):
    print(f"Recording {duration}s at {sr}Hz via ffmpeg ➜ PulseAudio…")
    cmd = [
        "ffmpeg",
        "-hide_banner", "-loglevel", "error",
        "-f", "pulse",                # use PulseAudio input
        "-i", "default",              # sets default as source
        "-ac", "1",                   # mono
        "-ar", str(sr),               # sample rate
        "-t", str(duration),          # duration
        str(path)
    ]
    subprocess.run(cmd, check=True)
    print(f"Saved mic input to {path}")


def run_step(cmd: list[str]):
    print(f"> running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, check=True)
    return proc

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dur", type=float, default=DEFAULT_DURATION, help="Record duration (s)")
    ap.add_argument("--wav",   type=Path, default="stand_app/outputs/raw_mic.wav")
    ap.add_argument("--tmp",   type=Path, default="stand_app/outputs/processed_audio.npy")
    ap.add_argument("--segs",  type=Path, default="stand_app/outputs/speech_segments.json")
    ap.add_argument("--txt",   type=Path, default="stand_app/outputs/transcript.csv")
    args = ap.parse_args()

    # ensure output dirs
    for p in (args.wav, args.tmp, args.segs, args.txt):
        p.parent.mkdir(parents=True, exist_ok=True)

    # 1) record
    record_to_wav(args.wav, args.dur, DEFAULT_SR)

    # 2) preprocess
    run_step(["python", "stand_app/preprocess_wav.py", str(args.wav), "--out", str(args.tmp)])

    # 3) vad detect
    run_step(["python", "stand_app/vad_detect.py", "--inp", str(args.tmp), "--npy", "--save", str(args.segs)])

    # 4) transcribe
    run_step([
      "python", "stand_app/transcribe_segments.py",
      "--inp",  str(args.tmp),
      str(args.segs),
      "--out",  str(args.txt)
    ])

    # 5) match commands
    run_step(["python", "stand_app/match_commands.py", "--in", str(args.txt)])

if __name__ == "__main__":
    main()

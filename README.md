## REX – a lean, offline-friendly voice assistant

REX is a lightweight, streaming voice assistant that runs transcription locally and controls your music player (YouTube Music Desktop or Spotify). It uses FFmpeg + PulseAudio for audio capture, Silero VAD to chunk utterances, Faster-Whisper for ASR, and a small regex router to map text to actions.

---

### Tech stack (what runs where)

| Stage               | Tech                                      | What it does                                   |
| ------------------- | ----------------------------------------- | ---------------------------------------------- |
| Audio capture       | `ffmpeg` + PulseAudio (Windows build)      | Streams 16 kHz mono PCM from the default mic   |
| Voice activity      | Silero VAD (PyTorch, TorchScript)          | Groups frames into utterances                  |
| Transcription       | Faster-Whisper (CTranslate2 backend)       | Speech → text on CPU or CUDA                   |
| Command routing     | Regex matcher (`rex_main/matcher.py`)      | Maps recognized text to handlers               |
| Media control       | YTMusic Desktop Companion API / Spotipy    | Sends actions to YTMD or Spotify               |
| Config & secrets    | `.env` via `python-dotenv`                 | Tokens and service endpoints                    |
| Logging             | Python logging + rotating file             | Console + `rex_main/logs/rex_log.log`          |

Key Python libs: `numpy`, `sounddevice`, `ffmpeg-python`, `pydub`, `torch`, `torchaudio`, `silero-vad`, `faster-whisper`, `ytmusicapi`, `spotipy`, `requests`, `python-dotenv` (see `requirements.txt`).

---

## Setup (Windows 10/11)

The project is optimized for Windows with a local PulseAudio server and optional CUDA. You can run fully on CPU if you prefer.

1) Install prerequisites

- Python 3.11+ (tested with 3.12)
- FFmpeg (add `ffmpeg` to PATH)
- PulseAudio for Windows: https://pgaskin.net/pulseaudio-win32/
  - During install, enable private network access and TCP module options.
  - Create/update your PulseAudio client config so apps reach the local server. You can use the provided `pulse_conf/client.conf`:
    - Contents: `default-server = tcp:host.docker.internal:4713`
    - Typical Windows path: `%AppData%/pulse/client.conf` (create directories if needed)
  - Start the PulseAudio daemon (the installer includes a GUI and service options).
- Optional GPU: Recent NVIDIA driver + CUDA 12 runtime compatible with PyTorch. The repo pins `nvidia-cudnn-cu12==9.5.1.17`.

2) Clone and create a virtual environment

```powershell
git clone https://github.com/David-Antolick/rex_voice_assistant.git
cd rex_voice_assistant
enter dev container
```

Notes:
- If you have issues installing `torch/torchaudio`, install the matching wheels first from https://pytorch.org/get-started/locally/ (then run `pip install -r requirements.txt` again to pick up the rest).
- CPU-only is supported. For GPU, ensure your PyTorch build supports CUDA and that drivers are up to date.

3) Configure media backends

YouTube Music Desktop Companion (YTMD):
- Install app: https://ytmdesktop.app (repo: https://github.com/ytmdesktop/ytmdesktop)
- In app Settings, enable:
  - “Companion server”
  - “Allow browser communication”
  - “Enable companion authorization”
- The default API runs on `host.docker.internal:9863`.
- Obtain a token (one-time):
  ```bash
curl http://host.docker.internal:9863/metadata
# → { "apiVersions": ["v1"] }

curl -X POST http://host.docker.internal:9863/api/v1/auth/requestcode \
  -H "Content-Type: application/json" \
  -d '{"appId":"rex_voice_assistant","appName":"Rex","appVersion":"1.0.0"}'
# → { "code": "1234" }

curl -X POST http://host.docker.internal:9863/api/v1/auth/request \
  -H "Content-Type: application/json" \
  -d '{"appId":"rex_voice_assistant","code":"THE_CODE_YOU_JUST_GOT"}'
# → { "token": "..." }
```
- Put values in `.env` (see below): `YTMD_TOKEN`, `YTMD_HOST`, `YTMD_PORT`.

Spotify (optional):
- Create an app at https://developer.spotify.com/dashboard
- Set Redirect URI to `http://127.0.0.1:8888/callback`
- Put secrets in `.env`: `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, `SPOTIPY_REDIRECT_URI`
- First run will open a browser to authorize. You may need to approve multiple times.

4) Create `.env`

Create a file named `.env` at the repo root or inside `rex_main/` with at least:

```ini
# YouTube Music Desktop Companion
YTMD_TOKEN="<token>"
YTMD_HOST="host.docker.internal"
YTMD_PORT="9863"

# Spotify (optional)
SPOTIPY_CLIENT_ID="<id>"
SPOTIPY_CLIENT_SECRET="<secret>"
SPOTIPY_REDIRECT_URI="http://127.0.0.1:8888/callback"

# Models cache (optional overrides)
HF_MODEL_HOME="<path to store models>"
```

The code loads environment variables via `python-dotenv` in `rex_main/commands.py`.

---

## Run

From the repo root:

```powershell
python -m rex_main.rex [--model small.en] [--device cuda|cpu] [--beam 1] [--debug] [--log_file rex_main/logs/rex_log.log]
```

Defaults are defined in `rex_main/rex.py`:
- `--model`: `small.en` (try `tiny.en` for smaller/faster, lower accuracy)
- `--device`: auto (prefers CUDA if available; otherwise CPU)
- `--beam`: 1 (increase for accuracy at the cost of latency)
- `--log_file`: rotating file at `rex_main/logs/rex_log.log`
- `--debug`: verbose logs

The pipeline:
- `AudioStream` (`rex_main/audio_stream.py`) streams 16 kHz mono PCM using `ffmpeg -f pulse -i default`.
- `SileroVAD` (`rex_main/vad_stream.py`) groups frames into utterances.
- `WhisperWorker` (`rex_main/whisper_worker.py`) transcribes to text (CPU or CUDA).
- `dispatch_command` (`rex_main/matcher.py`) regex-matches text and calls handlers in `rex_main/commands.py`.

---

## Built-in voice commands

| Phrase (examples)                 | Action                      |
| --------------------------------- | --------------------------- |
| "play music", "stop music"        | Play/pause                  |
| "next", "last/previous", "restart" | Track navigation            |
| "volume up/down", "volume N"      | Volume control              |
| "search <song> by <artist>"       | Play first search hit       |
| "switch to spotify"               | Switch backend to Spotify   |
| "switch to youtube music"         | Switch backend to YTMD      |

Add your own by editing `rex_main/matcher.py` (regex → handler name) and implementing the function in `rex_main/commands.py`.

---

## Configuration knobs

| Env var / flag            | What it affects                         |
| ------------------------- | --------------------------------------- |
| `--model`                 | Whisper model name (e.g., `small.en`)   |
| `--device`                | Force CPU/GPU decoding (`cpu`/`cuda`)   |
| `--beam`                  | Beam-search width                       |
| `HF_MODEL_HOME`           | Hugging Face model cache directory      |
| `YTMD_HOST`, `YTMD_PORT`  | YTMusic Desktop Companion API endpoint  |
| `YTMD_TOKEN`              | YTMD authorization token                |

---

## Logging

Controlled in `rex_main/rex.py`.
- Console at INFO by default (DEBUG with `--debug`)
- Rotating file via `--log_file` (default `rex_main/logs/rex_log.log`, 2 MB, 2 backups)

---

## Troubleshooting

- FFmpeg can’t open input `pulse`:
  - Ensure PulseAudio is running and `%AppData%/pulse/client.conf` points to the server (see Setup step 1). Restart PulseAudio after edits.
- YTMD 401/connection errors:
  - Re-check token and that Companion Server is enabled in YTMD settings.
  - Verify `YTMD_HOST`/`YTMD_PORT` and that `curl http://host.docker.internal:9863/metadata` responds.
- Spotify device not found:
  - Open the Spotify desktop app. First auth opens a browser; approve prompts. Then re-run.
- CUDA not used:
  - Run with `--device cuda` to force; ensure your PyTorch build has CUDA and drivers are current.

---

## Roadmap

- Dynamic hotword ("Hey Rex") with OpenWakeWord
- More commands (Spotify, application controls, clipping tools)

---

## Contributing

PRs welcome. Please keep changes small and document new config flags in this README. For larger features, open an issue to discuss design.

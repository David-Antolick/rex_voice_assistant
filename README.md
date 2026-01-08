## REX - Offline Voice-Controlled Music Assistant

REX is a lightweight, streaming voice assistant that runs transcription locally and controls your music player (YouTube Music Desktop or Spotify). It uses native audio capture via sounddevice, Silero VAD to chunk utterances, Faster-Whisper for ASR, and a regex router to map text to actions.

---

### Quick Start (3 steps)

```powershell
# 1. Install REX
pipx install rex-voice-assistant

# 2. Run the setup wizard
rex setup

# 3. Start REX
rex
```

That's it! The setup wizard will guide you through configuring your music service.

---

### Tech Stack

| Stage               | Tech                                      | What it does                                   |
| ------------------- | ----------------------------------------- | ---------------------------------------------- |
| Audio capture       | `sounddevice` (PortAudio)                  | Streams 16 kHz mono PCM from the default mic   |
| Voice activity      | Silero VAD (PyTorch, TorchScript)          | Groups frames into utterances                  |
| Transcription       | Faster-Whisper (CTranslate2 backend)       | Speech to text on CPU or CUDA                   |
| Command routing     | Regex matcher (`rex_main/matcher.py`)      | Maps recognized text to handlers               |
| Media control       | YTMusic Desktop Companion API / Spotipy    | Sends actions to YTMD or Spotify               |
| Config & secrets    | `~/.rex/config.yaml` + keyring             | Configuration and secure secret storage        |

---

### CLI Commands

```bash
rex              # Start the voice assistant
rex setup        # Interactive setup wizard
rex status       # Show configuration and service connectivity
rex test ytmd    # Test YouTube Music Desktop connection
rex test spotify # Test Spotify connection
rex dashboard    # Run metrics dashboard standalone
rex migrate --from-env  # Import settings from .env file
```

**Options for `rex` command:**
```
--model         Whisper model (tiny|base|small|medium|large, default: small.en)
--device        Force device (cuda|cpu, default: auto)
--beam          Beam size for decoding (default: 1)
--log-file      Path to log file
--debug         Enable verbose logging
--dashboard     Enable metrics dashboard at http://localhost:8080
--low-latency   Faster response time (250ms VAD timeout, may cut speech short)
```

---

### Prerequisites

#### Windows 10/11

1. **Python 3.10+** (tested with 3.12)
   ```powershell
   winget install Python.Python.3.12
   ```

2. **A microphone** - Any USB or built-in microphone will work

3. **Optional: NVIDIA GPU** for 5-10x faster transcription
   - Recent NVIDIA driver (no manual CUDA installation needed)
   - The setup wizard will offer to install CUDA PyTorch automatically

---

### Media Service Setup

#### YouTube Music Desktop (YTMD)

1. Install YTMD: https://ytmdesktop.app
2. In YTMD Settings, enable:
   - "Companion server"
   - "Allow browser communication"
   - "Enable companion authorization"
3. Run `rex setup` and follow the prompts to authenticate

#### Spotify

1. Create an app at https://developer.spotify.com/dashboard
2. Set Redirect URI to `http://127.0.0.1:8888/callback`
3. Run `rex setup` and enter your Client ID and Secret

---

### Voice Commands

| Phrase (examples)                 | Action                      |
| --------------------------------- | --------------------------- |
| "play music", "stop music"        | Play/pause                  |
| "next", "last/previous", "restart"| Track navigation            |
| "volume up/down", "volume N"      | Volume control              |
| "search <song> by <artist>"       | Play first search hit       |
| "switch to spotify"               | Switch backend to Spotify   |
| "switch to youtube music"         | Switch backend to YTMD      |
| "like", "dislike"                 | Thumbs up/down current track|
| "clip that", "save clip"          | Save clip (SteelSeries GG)  |

Add custom commands by editing `rex_main/matcher.py` and `rex_main/commands.py`.

#### SteelSeries Moments Clipping

REX integrates with SteelSeries GG Moments for voice-activated clipping:

1. Install [SteelSeries GG](https://steelseries.com/gg) and enable Moments
2. Run `rex setup` to register REX with GameSense
3. Enable REX autoclipping in GG: Moments → Settings → Apps → REX Voice Assistant
4. Say "clip that" while Moments is recording to save a clip

---

### Configuration

REX stores configuration in `~/.rex/`:

```
~/.rex/
  config.yaml     # Main configuration
  secrets.yaml    # Fallback secret storage (if keyring unavailable)
  logs/           # Log files
  models/         # Cached Whisper models
```

#### Environment Variable Overrides

| Variable              | Description                              |
| --------------------- | ---------------------------------------- |
| `REX_MODEL`           | Override Whisper model                   |
| `REX_DEVICE`          | Force CPU/GPU (`cpu`/`cuda`)             |
| `REX_SERVICE`         | Active service (`ytmd`/`spotify`/`none`) |
| `YTMD_TOKEN`          | YTMD authorization token                 |
| `YTMD_HOST`           | YTMD host (default: localhost)           |
| `YTMD_PORT`           | YTMD port (default: 9863)                |
| `SPOTIPY_CLIENT_ID`   | Spotify client ID                        |
| `SPOTIPY_CLIENT_SECRET`| Spotify client secret                   |
| `SPOTIPY_REDIRECT_URI`| Spotify OAuth redirect URI               |

---

### Troubleshooting

**No audio input detected:**
- Check Windows sound settings for default microphone
- Run `rex status` to see detected audio device
- Try running `rex setup` and use the audio test

**YTMD connection errors:**
- Run `rex test ytmd` to check connectivity
- Verify Companion Server is enabled in YTMD settings
- Re-run `rex setup` to get a new token

**Spotify device not found:**
- Open the Spotify desktop app before running REX
- Run `rex test spotify` to check connection
- Re-authenticate if needed

**CUDA not being used:**
- Run `rex setup` - it will detect your GPU and offer to install CUDA PyTorch
- Or manually install: `pipx runpip rex-voice-assistant install torch --index-url https://download.pytorch.org/whl/cu124 --force-reinstall`
- Verify: `rex` should auto-detect and log "CUDA detected, using GPU acceleration"

---

### Development

```bash
# Clone and install in development mode
git clone https://github.com/David-Antolick/rex_voice_assistant.git
cd rex_voice_assistant
pip install -e ".[dev]"

# Run tests
pytest

# Run directly
python -m rex_main.rex --debug
```

---

### Roadmap

- Dynamic hotword ("Hey Rex") with OpenWakeWord
- Discord integration (waiting for RPC API access)
- Application controls (open/close apps)
- Performance optimizations

---

### Contributing

PRs welcome. Please keep changes small and document new config flags in this README. For larger features, open an issue to discuss design.

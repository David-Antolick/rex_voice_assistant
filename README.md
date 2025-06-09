## REX – a lean, offline-friendly voice assistant

| Stage               | Tech                  | What it does                                 |
| ------------------- | --------------------- | -------------------------------------------- |
| **Audio capture**   | `ffmpeg` + PulseAudio | Streams 16-kHz mono PCM from the default mic |
| **Voice activity**  | Silero VAD (PyTorch)  | Slices input into spoken utterances          |
| **Transcription**   | *faster-whisper*      | Converts speech → text on CPU *or* CUDA      |
| **Command routing** | Regex matcher         | Maps text to handler functions               |
| **Execution**       | `commands.py`         | Sends actions to YTMusic Desktop & others    |

---

### Quick start

```bash
git clone https://github.com/your-name/rex
cd rex
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Follow setup outline in notes.txt

# Run with verbose logs to console and a rotating file
python -m rex_main --debug --log-file rex.log
```

> **Tip:** use `--help` to see model size, beam, and port overrides.

---

### Built-in voice commands

| Phrase (examples)           | Action                |
| --------------------------- | --------------------- |
| “play music”, “pause”       | Toggle playback       |
| “volume up / down / *N*”    | Set or step volume    |
| “next / last”               | Skip track            |
| “search *song* by *artist*” | Play first search hit |

Add your own by editing **`matcher.py`** – each regex points to a handler in **`commands.py`**.

---

### Logging

* Controlled centrally in **`rex.py`**
* Default `INFO` to console, `DEBUG` with `--debug`
* `--log-file` controls a 2 MB rotating file destination, default is `rex_main/logs/rex_log.log`


---

### Configuration knobs

| Env var / flag           | What it affects              |
| ------------------------ | ---------------------------- |
| `--model small.en`       | Whisper model name           |
| `--device cpu/cuda`           | Force CPU/GPU decoding           |
| `--beam 1`               | Beam-search width            |
| `HF_MODEL_HOME`          | Hugging Face cache dir       |
| `YTMD_PORT`, `YTMD_HOST` | YTMusic Desktop API location |

---

### Minimal API dependencies

* **YTMusic Desktop Remote** – runs on `host.docker.internal:9863` by default
* No cloud ASR; all models download once and run locally.

---

### Roadmap

* Dynamic hotword (“Hey Rex”) with OpenWakeWord
* Further commands, possibly for spotify, clipping softwares, or general application controls



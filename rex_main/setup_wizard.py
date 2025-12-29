"""setup_wizard.py
Interactive setup wizard for REX voice assistant.

Handles:
1. System check - Detect Python, FFmpeg, PulseAudio, CUDA
2. Audio setup - Offer PulseAudio install if missing
3. Media services - Choice of YTMD, Spotify, both, or none
4. YTMD setup - Authenticate with YouTube Music Desktop
5. Spotify setup - Guide through developer portal and OAuth
6. Model download - Offer to pre-download Whisper model
7. Audio test - Quick recording test
8. Write config - Save to ~/.rex/config.yaml
"""

from __future__ import annotations

import os
import sys
import time
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich import print as rprint

console = Console()


def run_wizard():
    """Run the interactive setup wizard."""
    console.print(Panel.fit(
        "[bold blue]REX Voice Assistant Setup Wizard[/bold blue]\n\n"
        "This wizard will help you configure REX for first-time use.",
        border_style="blue"
    ))
    console.print()

    # Step 1: System check
    if not _check_system():
        return

    # Step 2: Audio setup
    _setup_audio()

    # Step 3: Media services
    services = _choose_services()

    # Step 4 & 5: Configure chosen services
    secrets = {}
    service_config = {}

    if "ytmd" in services:
        ytmd_token = _setup_ytmd()
        if ytmd_token:
            secrets["ytmd_token"] = ytmd_token

    if "spotify" in services:
        spotify_creds = _setup_spotify()
        if spotify_creds:
            secrets.update(spotify_creds)

    # Step 6: Model download
    _setup_model()

    # Step 7: Audio test (optional)
    if Confirm.ask("\nWould you like to run a quick audio test?", default=False):
        _test_audio()

    # Step 8: Write config
    _write_config(services, secrets)

    console.print(Panel.fit(
        "[bold green]Setup Complete![/bold green]\n\n"
        "Run [cyan]rex[/cyan] to start the voice assistant.\n"
        "Run [cyan]rex status[/cyan] to check configuration.",
        border_style="green"
    ))


def _check_system() -> bool:
    """Check system requirements and display status."""
    console.print("[bold]Step 1: System Check[/bold]\n")

    table = Table(title="System Requirements")
    table.add_column("Component", style="cyan")
    table.add_column("Status")
    table.add_column("Details")

    all_ok = True

    # Python version
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 10)
    table.add_row(
        "Python",
        "[green]OK[/green]" if py_ok else "[red]FAIL[/red]",
        f"v{py_version}" + ("" if py_ok else " (need 3.10+)")
    )
    if not py_ok:
        all_ok = False

    # FFmpeg
    ffmpeg_path = shutil.which("ffmpeg")
    ffmpeg_ok = ffmpeg_path is not None
    table.add_row(
        "FFmpeg",
        "[green]OK[/green]" if ffmpeg_ok else "[red]MISSING[/red]",
        ffmpeg_path or "Install with: winget install Gyan.FFmpeg"
    )
    if not ffmpeg_ok:
        all_ok = False

    # PulseAudio (Windows)
    pulse_ok = False
    pulse_details = "Not detected"
    if sys.platform == "win32":
        # Check for PulseAudio in common locations
        pulse_paths = [
            Path(os.environ.get("PROGRAMFILES", "")) / "PulseAudio" / "bin" / "pulseaudio.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "PulseAudio" / "bin" / "pulseaudio.exe",
            Path("C:/PulseAudio/bin/pulseaudio.exe"),
        ]
        for p in pulse_paths:
            if p.exists():
                pulse_ok = True
                pulse_details = str(p.parent.parent)
                break
        if not pulse_ok:
            pulse_details = "Install from: https://pgaskin.net/pulseaudio-win32/"
    else:
        # Linux/Mac - check if pulseaudio is available
        if shutil.which("pulseaudio") or shutil.which("pactl"):
            pulse_ok = True
            pulse_details = "Available"

    table.add_row(
        "PulseAudio",
        "[green]OK[/green]" if pulse_ok else "[yellow]MISSING[/yellow]",
        pulse_details
    )

    # CUDA (optional)
    cuda_ok = False
    cuda_details = "Not detected (CPU mode will be used)"
    try:
        import torch
        if torch.cuda.is_available():
            cuda_ok = True
            cuda_details = f"CUDA {torch.version.cuda}, {torch.cuda.get_device_name(0)}"
    except ImportError:
        cuda_details = "PyTorch not installed yet"

    table.add_row(
        "CUDA (optional)",
        "[green]OK[/green]" if cuda_ok else "[yellow]N/A[/yellow]",
        cuda_details
    )

    console.print(table)
    console.print()

    if not all_ok:
        console.print("[red]Some required components are missing. Please install them and run setup again.[/red]")
        return False

    if not pulse_ok:
        console.print("[yellow]Warning: PulseAudio not detected. Audio capture may not work.[/yellow]")
        if not Confirm.ask("Continue anyway?", default=False):
            return False

    return True


def _setup_audio():
    """Set up audio configuration."""
    console.print("\n[bold]Step 2: Audio Setup[/bold]\n")

    if sys.platform == "win32":
        # Create PulseAudio client config
        pulse_conf_dir = Path(os.environ.get("APPDATA", "")) / "pulse"
        pulse_conf_file = pulse_conf_dir / "client.conf"

        if not pulse_conf_file.exists():
            console.print("Creating PulseAudio client configuration...")
            pulse_conf_dir.mkdir(parents=True, exist_ok=True)
            pulse_conf_file.write_text("default-server = tcp:localhost:4713\n")
            console.print(f"  Created: {pulse_conf_file}")
        else:
            console.print(f"  PulseAudio config exists: {pulse_conf_file}")

    console.print("[green]Audio setup complete.[/green]")


def _choose_services() -> list[str]:
    """Let user choose which media services to configure."""
    console.print("\n[bold]Step 3: Media Services[/bold]\n")

    console.print("REX can control the following music services:")
    console.print("  1. YouTube Music Desktop (YTMD) - Local app with Companion Server")
    console.print("  2. Spotify - Via Spotify Connect API")
    console.print("  3. Both services")
    console.print("  4. None (transcription-only mode)")
    console.print()

    choice = Prompt.ask(
        "Which service(s) would you like to configure?",
        choices=["1", "2", "3", "4"],
        default="1"
    )

    if choice == "1":
        return ["ytmd"]
    elif choice == "2":
        return ["spotify"]
    elif choice == "3":
        return ["ytmd", "spotify"]
    else:
        return []


def _setup_ytmd() -> Optional[str]:
    """Set up YouTube Music Desktop authentication."""
    console.print("\n[bold]Step 4: YouTube Music Desktop Setup[/bold]\n")

    console.print("To authenticate with YTMD, you need:")
    console.print("  1. YouTube Music Desktop app running")
    console.print("  2. Companion Server enabled in YTMD settings")
    console.print()

    if not Confirm.ask("Is YTMD running with Companion Server enabled?", default=True):
        console.print("[yellow]Please start YTMD and enable Companion Server, then run 'rex setup' again.[/yellow]")
        return None

    host = Prompt.ask("YTMD host", default="localhost")
    port = Prompt.ask("YTMD port", default="9863")

    base_url = f"http://{host}:{port}"

    # Step 1: Request auth code
    console.print("\nRequesting authentication code from YTMD...")

    try:
        import requests

        # Request code
        resp = requests.post(
            f"{base_url}/api/v1/auth/requestcode",
            json={"appId": "rex-voice-assistant", "appName": "REX Voice Assistant"},
            timeout=10
        )

        if resp.status_code != 200:
            console.print(f"[red]Failed to request code: HTTP {resp.status_code}[/red]")
            console.print(f"Response: {resp.text}")
            return None

        data = resp.json()
        code = data.get("code")

        if not code:
            console.print("[red]No code received from YTMD[/red]")
            return None

        console.print(Panel.fit(
            f"[bold yellow]Authorization Code: {code}[/bold yellow]\n\n"
            "Go to YTMD app and approve the connection request.",
            title="Action Required"
        ))

        # Wait for user to approve
        input("\nPress Enter after you've approved the request in YTMD...")

        # Exchange code for token
        console.print("Exchanging code for token...")
        resp = requests.post(
            f"{base_url}/api/v1/auth/request",
            json={"appId": "rex-voice-assistant", "code": code},
            timeout=10
        )

        if resp.status_code != 200:
            console.print(f"[red]Failed to get token: HTTP {resp.status_code}[/red]")
            return None

        data = resp.json()
        token = data.get("token")

        if not token:
            console.print("[red]No token received[/red]")
            return None

        console.print("[green]Successfully authenticated with YTMD![/green]")
        return token

    except requests.exceptions.ConnectionError:
        console.print(f"[red]Could not connect to YTMD at {base_url}[/red]")
        console.print("Make sure YTMD is running and Companion Server is enabled.")
        return None
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return None


def _setup_spotify() -> Optional[dict]:
    """Set up Spotify authentication."""
    console.print("\n[bold]Step 5: Spotify Setup[/bold]\n")

    console.print("To use Spotify, you need to create a Spotify Developer app:")
    console.print("  1. Go to: https://developer.spotify.com/dashboard")
    console.print("  2. Create a new app")
    console.print("  3. Set Redirect URI to: http://127.0.0.1:8888/callback")
    console.print("  4. Copy your Client ID and Client Secret")
    console.print()

    if not Confirm.ask("Have you created a Spotify Developer app?", default=False):
        console.print("[yellow]Please create the app and run 'rex setup' again.[/yellow]")
        return None

    client_id = Prompt.ask("Enter your Spotify Client ID")
    client_secret = Prompt.ask("Enter your Spotify Client Secret")

    if not client_id or not client_secret:
        console.print("[red]Client ID and Secret are required.[/red]")
        return None

    # Set up OAuth and trigger browser login
    console.print("\nOpening browser for Spotify login...")

    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth

        os.environ["SPOTIPY_CLIENT_ID"] = client_id
        os.environ["SPOTIPY_CLIENT_SECRET"] = client_secret
        os.environ["SPOTIPY_REDIRECT_URI"] = "http://127.0.0.1:8888/callback"

        sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            scope="user-modify-playback-state user-read-playback-state user-library-modify user-library-read",
            open_browser=True,
        ))

        # Test the connection
        user = sp.current_user()
        console.print(f"[green]Successfully authenticated as: {user.get('display_name', user.get('id'))}[/green]")

        return {
            "spotify_client_id": client_id,
            "spotify_client_secret": client_secret,
        }

    except Exception as e:
        console.print(f"[red]Spotify authentication failed: {e}[/red]")
        return None


def _setup_model():
    """Offer to pre-download the Whisper model."""
    console.print("\n[bold]Step 6: Model Setup[/bold]\n")

    console.print("REX uses the Whisper speech recognition model.")
    console.print("Models available: tiny, base, small, medium, large")
    console.print("  - small.en is recommended for English (good balance of speed/accuracy)")
    console.print()

    if not Confirm.ask("Would you like to pre-download the model now?", default=True):
        console.print("Model will be downloaded on first run.")
        return

    model_name = Prompt.ask("Model to download", default="small.en")

    console.print(f"\nDownloading {model_name} model...")

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Downloading model...", total=None)

            from faster_whisper import WhisperModel

            # This will download if not cached
            model = WhisperModel(model_name, device="cpu", compute_type="int8")

            progress.update(task, description="Model downloaded!")

        console.print(f"[green]Model {model_name} is ready![/green]")

    except Exception as e:
        console.print(f"[yellow]Could not download model: {e}[/yellow]")
        console.print("Model will be downloaded on first run.")


def _test_audio():
    """Run a quick audio test."""
    console.print("\n[bold]Step 7: Audio Test[/bold]\n")

    console.print("Testing audio capture for 3 seconds...")
    console.print("Please speak into your microphone.\n")

    try:
        import numpy as np

        # Simple test using ffmpeg
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-loglevel", "error",
            "-f", "pulse", "-i", "default",
            "-ac", "1", "-ar", "16000",
            "-t", "3",  # 3 seconds
            "-f", "s16le", "pipe:1"
        ]

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Recording...", total=None)

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10
            )

            progress.update(task, description="Processing...")

        if result.returncode == 0 and len(result.stdout) > 0:
            # Convert to numpy and check audio level
            audio = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0
            max_level = np.max(np.abs(audio))
            rms = np.sqrt(np.mean(audio**2))

            if max_level > 0.01:
                console.print(f"[green]Audio captured successfully![/green]")
                console.print(f"  Peak level: {max_level:.2%}")
                console.print(f"  RMS level: {rms:.2%}")
            else:
                console.print("[yellow]Audio captured but level is very low.[/yellow]")
                console.print("Check your microphone settings.")
        else:
            console.print("[red]No audio captured.[/red]")
            if result.stderr:
                console.print(f"Error: {result.stderr.decode()}")

    except subprocess.TimeoutExpired:
        console.print("[red]Audio test timed out.[/red]")
    except Exception as e:
        console.print(f"[red]Audio test failed: {e}[/red]")


def _write_config(services: list[str], secrets: dict):
    """Write configuration to ~/.rex/config.yaml."""
    console.print("\n[bold]Step 8: Saving Configuration[/bold]\n")

    from rex_main.config import CONFIG_DIR, save_config, save_secrets, ensure_config_dir

    ensure_config_dir()

    # Build config
    config = {
        "audio": {
            "sample_rate": 16000,
            "frame_ms": 32,
            "pulse_server": "tcp:localhost:4713",
        },
        "model": {
            "name": "small.en",
            "device": "auto",
            "beam_size": 1,
            "cache_dir": str(CONFIG_DIR / "models"),
        },
        "services": {
            "active": services[0] if services else "none",
            "ytmd": {
                "host": "localhost",
                "port": 9863,
            },
            "spotify": {
                "redirect_uri": "http://127.0.0.1:8888/callback",
            },
        },
        "logging": {
            "level": "INFO",
            "file": str(CONFIG_DIR / "logs" / "rex.log"),
        },
    }

    # Save config
    save_config(config)
    console.print(f"  Configuration saved to: {CONFIG_DIR / 'config.yaml'}")

    # Save secrets
    if secrets:
        save_secrets(secrets)
        console.print(f"  Secrets saved securely")

    console.print("[green]Configuration complete![/green]")


if __name__ == "__main__":
    run_wizard()

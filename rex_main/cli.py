"""cli.py
Unified CLI entry point for REX voice assistant.

Commands:
    rex           - Run the voice assistant (default)
    rex setup     - Interactive setup wizard
    rex status    - Show configuration and service connectivity
    rex test      - Test a specific service (ytmd/spotify)
    rex migrate   - Import existing .env to new config
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


@click.group(invoke_without_command=True)
@click.option("--model", default="small.en", help="Whisper model size (tiny|base|small|medium|large)")
@click.option("--device", default="auto", type=click.Choice(["cuda", "cpu", "auto"]), help="Device for inference (auto=CPU, use cuda for GPU)")
@click.option("--beam", default=1, type=int, help="Beam size for Whisper decoding")
@click.option("--log-file", default=None, help="Path to write rotating logs")
@click.option("--debug", is_flag=True, help="Enable verbose logging")
@click.pass_context
def cli(ctx: click.Context, model: str, device: str, beam: int, log_file: Optional[str], debug: bool):
    """REX - Voice-controlled music assistant.

    Run without a subcommand to start the voice assistant.
    """
    ctx.ensure_object(dict)
    ctx.obj["model"] = model
    ctx.obj["device"] = device
    ctx.obj["beam"] = beam
    ctx.obj["log_file"] = log_file
    ctx.obj["debug"] = debug

    # If no subcommand, run the assistant
    if ctx.invoked_subcommand is None:
        ctx.invoke(run)


@cli.command()
@click.pass_context
def run(ctx: click.Context):
    """Run the REX voice assistant."""
    from rex_main.config import load_config, get_log_file_path

    config = load_config()

    # Build options namespace-like object for compatibility
    class Options:
        pass

    opts = Options()
    opts.model = ctx.obj.get("model") or config.get("model", {}).get("name", "small.en")
    opts.device = ctx.obj.get("device") or config.get("model", {}).get("device", "auto")
    opts.beam = ctx.obj.get("beam") or config.get("model", {}).get("beam_size", 1)
    opts.log_file = ctx.obj.get("log_file") or get_log_file_path(config)
    opts.debug = ctx.obj.get("debug", False)

    # Configure services from config
    from rex_main.commands import configure_from_config
    configure_from_config(config)

    # Import and run main
    from rex_main.rex import run_assistant

    try:
        asyncio.run(run_assistant(opts, config))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(0)


@cli.command()
def setup():
    """Interactive setup wizard for REX."""
    from rex_main.setup_wizard import run_wizard
    run_wizard()


@cli.command()
def status():
    """Show current configuration and service connectivity."""
    from rex_main.config import load_config, get_secrets, CONFIG_DIR

    config = load_config()
    secrets = get_secrets(config)

    console.print(Panel.fit("[bold blue]REX Status[/bold blue]"))

    # Config file location
    config_file = CONFIG_DIR / "config.yaml"
    console.print(f"\n[bold]Configuration:[/bold]")
    console.print(f"  Config file: {config_file} ({'exists' if config_file.exists() else '[red]not found[/red]'})")

    # Active service
    active = config.get("services", {}).get("active", "none")
    console.print(f"  Active service: [cyan]{active}[/cyan]")

    # Model settings
    model_cfg = config.get("model", {})
    console.print(f"\n[bold]Model:[/bold]")
    console.print(f"  Name: {model_cfg.get('name', 'small.en')}")
    console.print(f"  Device: {model_cfg.get('device', 'auto')}")

    # Service status table
    table = Table(title="\nService Connectivity")
    table.add_column("Service", style="cyan")
    table.add_column("Configured", style="green")
    table.add_column("Status")

    # YTMD status
    ytmd_token = secrets.get("ytmd_token")
    ytmd_configured = "Yes" if ytmd_token else "No"
    ytmd_status = "[green]Ready[/green]" if ytmd_token else "[yellow]Not configured[/yellow]"
    if ytmd_token:
        # Try to connect
        try:
            import requests
            host = config.get("services", {}).get("ytmd", {}).get("host", "localhost")
            port = config.get("services", {}).get("ytmd", {}).get("port", 9863)
            resp = requests.get(f"http://{host}:{port}/api/v1/state",
                              headers={"Authorization": ytmd_token}, timeout=2)
            if resp.status_code == 200:
                ytmd_status = "[green]Connected[/green]"
            else:
                ytmd_status = f"[red]Error ({resp.status_code})[/red]"
        except Exception as e:
            ytmd_status = f"[red]Offline[/red]"
    table.add_row("YouTube Music Desktop", ytmd_configured, ytmd_status)

    # Spotify status
    spotify_id = secrets.get("spotify_client_id")
    spotify_secret = secrets.get("spotify_client_secret")
    spotify_configured = "Yes" if (spotify_id and spotify_secret) else "No"
    spotify_status = "[green]Ready[/green]" if (spotify_id and spotify_secret) else "[yellow]Not configured[/yellow]"
    table.add_row("Spotify", spotify_configured, spotify_status)

    console.print(table)

    # Audio settings
    audio_cfg = config.get("audio", {})
    console.print(f"\n[bold]Audio:[/bold]")
    console.print(f"  Sample rate: {audio_cfg.get('sample_rate', 16000)} Hz")

    # Show audio device info
    try:
        import sounddevice as sd
        default_input = sd.default.device[0]
        if default_input is not None and default_input >= 0:
            dev_info = sd.query_devices(default_input)
            console.print(f"  Input device: {dev_info['name']}")
        else:
            console.print(f"  Input device: [yellow]No default set[/yellow]")
    except Exception:
        console.print(f"  Input device: [yellow]Could not detect[/yellow]")


@cli.command()
@click.argument("service", type=click.Choice(["ytmd", "spotify"]))
def test(service: str):
    """Test connectivity to a specific service."""
    from rex_main.config import load_config, get_secrets

    config = load_config()
    secrets = get_secrets(config)

    if service == "ytmd":
        console.print("[bold]Testing YouTube Music Desktop connection...[/bold]")
        token = secrets.get("ytmd_token")
        if not token:
            console.print("[red]YTMD token not configured. Run 'rex setup' first.[/red]")
            return

        try:
            import requests
            host = config.get("services", {}).get("ytmd", {}).get("host", "localhost")
            port = config.get("services", {}).get("ytmd", {}).get("port", 9863)

            # Test state endpoint
            resp = requests.get(f"http://{host}:{port}/api/v1/state",
                              headers={"Authorization": token}, timeout=5)
            if resp.status_code == 200:
                state = resp.json()
                console.print("[green]Connected successfully![/green]")
                player = state.get("player", {})
                if player.get("trackState") == 1:
                    track = player.get("videoDetails", {})
                    console.print(f"  Now playing: {track.get('title', 'Unknown')} by {track.get('author', 'Unknown')}")
                else:
                    console.print("  Player is paused/stopped")
            else:
                console.print(f"[red]Connection failed: HTTP {resp.status_code}[/red]")
        except requests.exceptions.ConnectionError:
            console.print("[red]Could not connect. Is YouTube Music Desktop running?[/red]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

    elif service == "spotify":
        console.print("[bold]Testing Spotify connection...[/bold]")
        client_id = secrets.get("spotify_client_id")
        client_secret = secrets.get("spotify_client_secret")

        if not client_id or not client_secret:
            console.print("[red]Spotify credentials not configured. Run 'rex setup' first.[/red]")
            return

        try:
            import spotipy
            from spotipy.oauth2 import SpotifyOAuth

            redirect_uri = config.get("services", {}).get("spotify", {}).get(
                "redirect_uri", "http://127.0.0.1:8888/callback"
            )

            sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope="user-modify-playback-state user-read-playback-state user-library-modify"
            ))

            # Try to get current user
            user = sp.current_user()
            console.print(f"[green]Connected successfully![/green]")
            console.print(f"  Logged in as: {user.get('display_name', user.get('id'))}")

            # Check for active devices
            devices = sp.devices()
            if devices.get("devices"):
                console.print(f"  Active devices: {len(devices['devices'])}")
                for dev in devices["devices"]:
                    active = " [active]" if dev.get("is_active") else ""
                    console.print(f"    - {dev['name']} ({dev['type']}){active}")
            else:
                console.print("  [yellow]No active devices found[/yellow]")

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.option("--from-env", "from_env", is_flag=True, help="Import from existing .env file")
def migrate(from_env: bool):
    """Migrate configuration from legacy formats."""
    from rex_main.config import CONFIG_DIR, save_secrets

    if from_env:
        console.print("[bold]Migrating from .env file...[/bold]")

        # Look for .env in common locations
        env_paths = [
            Path.cwd() / ".env",
            Path.cwd() / "rex_main" / ".env",
            Path(__file__).parent / ".env",
        ]

        env_file = None
        for path in env_paths:
            if path.exists():
                env_file = path
                break

        if not env_file:
            console.print("[red]No .env file found[/red]")
            return

        console.print(f"  Found: {env_file}")

        # Parse .env file
        from dotenv import dotenv_values
        env_vars = dotenv_values(env_file)

        # Extract and save secrets
        secrets_to_save = {}

        if env_vars.get("YTMD_TOKEN"):
            secrets_to_save["ytmd_token"] = env_vars["YTMD_TOKEN"]
            console.print("  [green]Found YTMD token[/green]")

        if env_vars.get("SPOTIPY_CLIENT_ID"):
            secrets_to_save["spotify_client_id"] = env_vars["SPOTIPY_CLIENT_ID"]
            console.print("  [green]Found Spotify client ID[/green]")

        if env_vars.get("SPOTIPY_CLIENT_SECRET"):
            secrets_to_save["spotify_client_secret"] = env_vars["SPOTIPY_CLIENT_SECRET"]
            console.print("  [green]Found Spotify client secret[/green]")

        if secrets_to_save:
            save_secrets(secrets_to_save)
            console.print(f"\n[green]Migrated {len(secrets_to_save)} secrets to {CONFIG_DIR / 'secrets.yaml'}[/green]")

            # Update config with service settings
            from rex_main.config import load_config, save_config
            config = load_config()

            if env_vars.get("YTMD_HOST"):
                config.setdefault("services", {}).setdefault("ytmd", {})["host"] = env_vars["YTMD_HOST"]
            if env_vars.get("YTMD_PORT"):
                config.setdefault("services", {}).setdefault("ytmd", {})["port"] = int(env_vars["YTMD_PORT"])
            if env_vars.get("SPOTIPY_REDIRECT_URI"):
                config.setdefault("services", {}).setdefault("spotify", {})["redirect_uri"] = env_vars["SPOTIPY_REDIRECT_URI"]

            # Set active service based on what's configured
            if "ytmd_token" in secrets_to_save:
                config.setdefault("services", {})["active"] = "ytmd"
            elif "spotify_client_id" in secrets_to_save:
                config.setdefault("services", {})["active"] = "spotify"

            save_config(config)
            console.print("[green]Updated config.yaml with service settings[/green]")
        else:
            console.print("[yellow]No secrets found to migrate[/yellow]")
    else:
        console.print("Use --from-env to migrate from a .env file")


def main():
    """Entry point for the rex command."""
    cli()


if __name__ == "__main__":
    main()

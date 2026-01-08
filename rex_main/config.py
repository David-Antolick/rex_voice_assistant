"""config.py
Configuration management for REX voice assistant.

Configuration is loaded from multiple sources with the following priority:
1. Environment variables (highest priority)
2. User config file (~/.rex/config.yaml)
3. Default config (rex_main/default_config.yaml)

Secrets are stored using keyring when available, with fallback to ~/.rex/secrets.yaml
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger("rex.config")

# Configuration directory
CONFIG_DIR = Path.home() / ".rex"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
SECRETS_FILE = CONFIG_DIR / "secrets.yaml"
DEFAULT_CONFIG = Path(__file__).parent / "default_config.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries, with override taking precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _expand_path(path: str) -> str:
    """Expand ~ and environment variables in a path."""
    return os.path.expandvars(os.path.expanduser(path))


def load_defaults() -> dict:
    """Load default configuration from package."""
    if DEFAULT_CONFIG.exists():
        with open(DEFAULT_CONFIG, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


def load_user_config() -> dict:
    """Load user configuration from ~/.rex/config.yaml."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


def load_config() -> dict:
    """Load merged configuration from defaults and user config.

    Returns:
        dict: Merged configuration dictionary
    """
    defaults = load_defaults()
    user_config = load_user_config()

    config = _deep_merge(defaults, user_config)

    # Apply environment variable overrides
    env_overrides = _get_env_overrides()
    config = _deep_merge(config, env_overrides)

    return config


def _get_env_overrides() -> dict:
    """Get configuration overrides from environment variables."""
    overrides: dict = {}

    # Model overrides
    if os.getenv("REX_MODEL"):
        overrides.setdefault("model", {})["name"] = os.getenv("REX_MODEL")
    if os.getenv("REX_DEVICE"):
        overrides.setdefault("model", {})["device"] = os.getenv("REX_DEVICE")

    # Audio overrides
    if os.getenv("PULSE_SERVER"):
        overrides.setdefault("audio", {})["pulse_server"] = os.getenv("PULSE_SERVER")

    # Service overrides
    if os.getenv("REX_SERVICE"):
        overrides.setdefault("services", {})["active"] = os.getenv("REX_SERVICE")

    # YTMD overrides
    if os.getenv("YTMD_HOST"):
        overrides.setdefault("services", {}).setdefault("ytmd", {})["host"] = os.getenv("YTMD_HOST")
    if os.getenv("YTMD_PORT"):
        overrides.setdefault("services", {}).setdefault("ytmd", {})["port"] = int(os.getenv("YTMD_PORT"))

    # Spotify overrides
    if os.getenv("SPOTIPY_REDIRECT_URI"):
        overrides.setdefault("services", {}).setdefault("spotify", {})["redirect_uri"] = os.getenv("SPOTIPY_REDIRECT_URI")

    return overrides


def save_config(config: dict) -> None:
    """Save configuration to ~/.rex/config.yaml."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    logger.info(f"Configuration saved to {CONFIG_FILE}")


def get_secrets(config: Optional[dict] = None) -> dict:
    """Get secrets from keyring or fallback to secrets.yaml.

    Args:
        config: Optional config dict (unused, for future extension)

    Returns:
        dict: Dictionary of secrets
    """
    secrets = {}

    # Try keyring first
    try:
        import keyring
        ytmd_token = keyring.get_password("rex", "ytmd_token")
        if ytmd_token:
            secrets["ytmd_token"] = ytmd_token

        spotify_id = keyring.get_password("rex", "spotify_client_id")
        if spotify_id:
            secrets["spotify_client_id"] = spotify_id

        spotify_secret = keyring.get_password("rex", "spotify_client_secret")
        if spotify_secret:
            secrets["spotify_client_secret"] = spotify_secret

    except Exception as e:
        logger.debug(f"Keyring not available: {e}")

    # Fallback to secrets.yaml for any missing secrets
    if SECRETS_FILE.exists():
        try:
            with open(SECRETS_FILE, "r") as f:
                file_secrets = yaml.safe_load(f) or {}
                for key, value in file_secrets.items():
                    if key not in secrets:
                        secrets[key] = value
        except Exception as e:
            logger.warning(f"Failed to read secrets file: {e}")

    # Also check environment variables (highest priority for secrets)
    if os.getenv("YTMD_TOKEN"):
        secrets["ytmd_token"] = os.getenv("YTMD_TOKEN")
    if os.getenv("SPOTIPY_CLIENT_ID"):
        secrets["spotify_client_id"] = os.getenv("SPOTIPY_CLIENT_ID")
    if os.getenv("SPOTIPY_CLIENT_SECRET"):
        secrets["spotify_client_secret"] = os.getenv("SPOTIPY_CLIENT_SECRET")

    return secrets


def save_secrets(secrets: dict, use_keyring: bool = True) -> None:
    """Save secrets to keyring or fallback to secrets.yaml.

    Args:
        secrets: Dictionary of secrets to save
        use_keyring: Whether to try using keyring (default True)
    """
    keyring_available = False

    if use_keyring:
        try:
            import keyring

            for key, value in secrets.items():
                keyring.set_password("rex", key, value)

            keyring_available = True
            logger.info("Secrets saved to system keyring")
        except Exception as e:
            logger.debug(f"Keyring not available, falling back to file: {e}")

    if not keyring_available:
        # Fallback to secrets.yaml
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        # Load existing secrets and merge
        existing = {}
        if SECRETS_FILE.exists():
            with open(SECRETS_FILE, "r") as f:
                existing = yaml.safe_load(f) or {}

        existing.update(secrets)

        with open(SECRETS_FILE, "w") as f:
            yaml.dump(existing, f, default_flow_style=False)

        # Set restrictive permissions on secrets file (Unix only)
        try:
            SECRETS_FILE.chmod(0o600)
        except Exception:
            pass

        logger.info(f"Secrets saved to {SECRETS_FILE}")


def get_log_file_path(config: dict) -> str:
    """Get the log file path from config, expanding ~ and creating directories."""
    log_file = config.get("logging", {}).get("file", "~/.rex/logs/rex.log")
    log_path = Path(_expand_path(log_file))

    # Create log directory if it doesn't exist
    log_path.parent.mkdir(parents=True, exist_ok=True)

    return str(log_path)


def ensure_config_dir() -> None:
    """Ensure the configuration directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (CONFIG_DIR / "logs").mkdir(exist_ok=True)
    (CONFIG_DIR / "models").mkdir(exist_ok=True)

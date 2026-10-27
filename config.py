"""Configuration management for RecCLI."""

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# Default configuration values
DEFAULT_FPS: int = 60
DEFAULT_QUALITY: str = "high"
DEFAULT_OUTPUT: str = str(Path.home() / "Videos" / "RecCLI")
DEFAULT_COUNTDOWN: int = 3
DEFAULT_FILENAME_FORMAT: str = "recording_{YYYY}-{MM}-{DD}_{HH}-{MM}-{SS}"


def get_config_path() -> Path:
    """Return the per-user Linux config path."""
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "reccli" / "config.json"

VALID_FPS_OPTIONS: list[int] = [15, 24, 30, 60]
VALID_QUALITY_OPTIONS: list[str] = ["low", "medium", "high"]


@dataclass
class Config:
    """Application configuration stored as a dataclass."""

    fps: int = DEFAULT_FPS
    quality: str = DEFAULT_QUALITY
    output_folder: str = DEFAULT_OUTPUT
    countdown: int = DEFAULT_COUNTDOWN
    filename_format: str = DEFAULT_FILENAME_FORMAT

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to a dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Create a Config instance from a dictionary with validation."""
        fps = data.get("fps", DEFAULT_FPS)
        if fps not in VALID_FPS_OPTIONS:
            fps = DEFAULT_FPS

        quality = data.get("quality", DEFAULT_QUALITY).lower()
        if quality not in VALID_QUALITY_OPTIONS:
            quality = DEFAULT_QUALITY

        output_folder = data.get("output_folder", DEFAULT_OUTPUT)
        if not isinstance(output_folder, str) or not output_folder.strip():
            output_folder = DEFAULT_OUTPUT

        countdown = data.get("countdown", DEFAULT_COUNTDOWN)
        if not isinstance(countdown, int) or countdown < 0 or countdown > 10:
            countdown = DEFAULT_COUNTDOWN

        filename_format = data.get("filename_format", DEFAULT_FILENAME_FORMAT)
        if not isinstance(filename_format, str) or not filename_format.strip():
            filename_format = DEFAULT_FILENAME_FORMAT

        return cls(
            fps=fps,
            quality=quality,
            output_folder=output_folder,
            countdown=countdown,
            filename_format=filename_format,
        )


def load_config() -> Config:
    """Load user settings, migrating the old project-local file once."""
    config_path = get_config_path()

    if not config_path.exists():
        legacy_path = Path(__file__).resolve().with_name("config.json")
        if legacy_path.exists():
            try:
                with open(legacy_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                config = Config.from_dict(data)
                # Preserve the old project-relative output folder after moving
                # settings out of the project directory.
                output_path = Path(config.output_folder)
                if not output_path.is_absolute():
                    config.output_folder = str((legacy_path.parent / output_path).resolve())
                save_config(config)
                return config
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass

    if not config_path.exists():
        config = Config()
        save_config(config)
        return config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        config = Config.from_dict(data)
        return config
    except (json.JSONDecodeError, TypeError, ValueError):
        # Invalid config file — reset to defaults
        config = Config()
        save_config(config)
        return config


def save_config(config: Config) -> None:
    """Save configuration to config.json."""
    try:
        config_path = get_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, indent=4)
    except OSError as e:
        from rich.console import Console
        Console().print(f"[red]Error saving configuration: {e}[/red]")


def reset_config() -> Config:
    """Reset configuration to defaults and save."""
    config = Config()
    save_config(config)
    return config

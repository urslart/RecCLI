"""Utility functions for RecCLI."""

import os
import shutil
import subprocess
import sys
import select
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console

console = Console()


def check_ffmpeg() -> bool:
    """Check if FFmpeg is available on the system PATH."""
    return shutil.which("ffmpeg") is not None


def ensure_output_folder(folder: str) -> Path:
    """Ensure the output folder exists, creating it if necessary."""
    path = Path(folder)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        console.print(f"[red]Error creating output folder '{folder}': {e}[/red]")
        console.print("[yellow]Falling back to 'Recordings/' folder.[/yellow]")
        path = Path("Recordings")
        path.mkdir(parents=True, exist_ok=True)
    return path


def generate_filename(fmt: str, extension: str) -> str:
    """Generate a filename from a format string and the current timestamp.

    Supported placeholders:
        {YYYY} - 4-digit year
        {MM}   - 2-digit month
        {DD}   - 2-digit day
        {HH}   - 2-digit hour (24h)
        {MIN}  - 2-digit minute  (use MIN to avoid collision with MM=month)
        {SS}   - 2-digit second

    Legacy support:
        The format string may also use the pattern with duplicate {MM} —
        the first {MM} is treated as month, the second as minute when the
        default format "recording_{YYYY}-{MM}-{DD}_{HH}-{MM}-{SS}" is used.
    """
    now = datetime.now()

    # Handle the default format which reuses {MM} for both month and minute
    # by doing sequential replacement
    name = fmt
    name = name.replace("{YYYY}", now.strftime("%Y"), 1)

    # First {MM} = month
    name = name.replace("{MM}", now.strftime("%m"), 1)

    name = name.replace("{DD}", now.strftime("%d"), 1)
    name = name.replace("{HH}", now.strftime("%H"), 1)

    # Second {MM} = minute (if still present) or {MIN}
    name = name.replace("{MM}", now.strftime("%M"), 1)
    name = name.replace("{MIN}", now.strftime("%M"), 1)

    name = name.replace("{SS}", now.strftime("%S"), 1)

    return f"{name}.{extension}"


def format_duration(seconds: float) -> str:
    """Format seconds into HH:MM:SS string."""
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_file_size(size_bytes: int) -> str:
    """Format file size into a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    else:
        return f"{size_bytes / (1024 ** 3):.2f} GB"


def open_folder(path: str) -> None:
    """Open a folder in the platform's default file manager."""
    folder = Path(path).resolve()
    try:
        os.startfile(str(folder))  # type: ignore[attr-defined]
    except AttributeError:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        try:
            subprocess.Popen([opener, str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            console.print(f"[red]Could not open folder: {e}[/red]")
    except OSError as e:
        console.print(f"[red]Could not open folder: {e}[/red]")


def clear_screen() -> None:
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def read_key(timeout: float = 0.05) -> str:
    """Read one terminal key without blocking on Windows or Unix terminals."""
    if os.name == "nt":
        import msvcrt
        if msvcrt.kbhit():
            return msvcrt.getch().decode("utf-8", errors="ignore").lower()
        time.sleep(timeout)
        return ""

    import termios
    import tty
    if not sys.stdin.isatty():
        time.sleep(timeout)
        return ""
    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        return sys.stdin.read(1).lower() if ready else ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)


def get_quality_crf(quality: str) -> int:
    """Return the FFmpeg CRF value for a given quality level.

    Lower CRF = higher quality.
    """
    mapping = {
        "low": 28,
        "medium": 23,
        "high": 18,
    }
    return mapping.get(quality.lower(), 23)


def get_quality_preset(quality: str) -> str:
    """Return the FFmpeg preset for a given quality level."""
    mapping = {
        "low": "ultrafast",
        "medium": "fast",
        "high": "medium",
    }
    return mapping.get(quality.lower(), "fast")

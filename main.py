#!/usr/bin/env python3
"""RecCLI — A lightweight screen and audio recorder for the terminal.

Usage:
    python main.py

Requirements:
    - Python 3.10+
    - Windows 10/11 or Linux
    - FFmpeg (on PATH)
    - pip install mss sounddevice soundfile rich numpy
"""

import sys

from rich.console import Console

console = Console()


def main() -> None:
    """Entry point for RecCLI."""
    # Check Python version
    if sys.version_info < (3, 10):
        console.print(
            "[red]RecCLI requires Python 3.10 or later.[/red]"
        )
        sys.exit(1)

    # Import and run the menu
    try:
        from menu import run
        run()
    except ImportError as e:
        console.print(
            f"[red]Missing dependency: {e}[/red]\n"
            "[yellow]Run: pip install -r requirements.txt[/yellow]"
        )
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Fatal error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()

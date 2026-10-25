"""Settings menu for RecCLI."""

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from config import (
    Config,
    VALID_FPS_OPTIONS,
    VALID_QUALITY_OPTIONS,
    save_config,
    reset_config,
)
from utils import clear_screen

console = Console()


def settings_menu(config: Config) -> Config:
    """Display the settings menu and handle user input.

    Returns the (possibly modified) Config.
    """
    while True:
        clear_screen()

        settings_text = (
            "[bold cyan]Settings[/bold cyan]\n"
            "\n"
            f"  [white]1.[/white] FPS              [dim]({config.fps})[/dim]\n"
            f"  [white]2.[/white] Video Quality     [dim]({config.quality.capitalize()})[/dim]\n"
            f"  [white]3.[/white] Output Folder     [dim]({config.output_folder})[/dim]\n"
            f"  [white]4.[/white] Countdown         [dim]({config.countdown}s)[/dim]\n"
            f"  [white]5.[/white] Filename Format   [dim]({config.filename_format})[/dim]\n"
            f"  [white]6.[/white] Reset Settings\n"
            f"  [white]7.[/white] Back\n"
        )

        console.print(Panel(settings_text, border_style="bright_blue"))
        choice = Prompt.ask("Select an option", choices=["1","2","3","4","5","6","7"], default="7")

        if choice == "1":
            config = _change_fps(config)
        elif choice == "2":
            config = _change_quality(config)
        elif choice == "3":
            config = _change_output_folder(config)
        elif choice == "4":
            config = _change_countdown(config)
        elif choice == "5":
            config = _change_filename_format(config)
        elif choice == "6":
            config = _reset_settings()
        elif choice == "7":
            break

    return config


def _change_fps(config: Config) -> Config:
    """Change the FPS setting."""
    options_str = ", ".join(str(f) for f in VALID_FPS_OPTIONS)
    console.print(f"\n[cyan]Available FPS options:[/cyan] {options_str}")

    choice = Prompt.ask(
        "Enter FPS",
        choices=[str(f) for f in VALID_FPS_OPTIONS],
        default=str(config.fps),
    )
    config.fps = int(choice)
    save_config(config)
    console.print(f"[green]FPS set to {config.fps}.[/green]")
    return config


def _change_quality(config: Config) -> Config:
    """Change the video quality setting."""
    options_str = ", ".join(q.capitalize() for q in VALID_QUALITY_OPTIONS)
    console.print(f"\n[cyan]Available quality options:[/cyan] {options_str}")

    choice = Prompt.ask(
        "Enter quality",
        choices=VALID_QUALITY_OPTIONS,
        default=config.quality,
    )
    config.quality = choice.lower()
    save_config(config)
    console.print(f"[green]Quality set to {config.quality.capitalize()}.[/green]")
    return config


def _change_output_folder(config: Config) -> Config:
    """Change the output folder setting."""
    console.print(f"\n[cyan]Current output folder:[/cyan] {config.output_folder}")

    folder = Prompt.ask("Enter new output folder", default=config.output_folder)
    folder = folder.strip()
    if folder:
        config.output_folder = folder
        save_config(config)
        console.print(f"[green]Output folder set to '{config.output_folder}'.[/green]")
    else:
        console.print("[yellow]Invalid folder name. No changes made.[/yellow]")
    return config


def _change_countdown(config: Config) -> Config:
    """Change the countdown before recording."""
    console.print(f"\n[cyan]Current countdown:[/cyan] {config.countdown}s")
    console.print("[dim]Enter a value between 0 and 10.[/dim]")

    value = Prompt.ask("Enter countdown (seconds)", default=str(config.countdown))
    try:
        countdown = int(value)
        if 0 <= countdown <= 10:
            config.countdown = countdown
            save_config(config)
            console.print(f"[green]Countdown set to {config.countdown}s.[/green]")
        else:
            console.print("[yellow]Value must be between 0 and 10.[/yellow]")
    except ValueError:
        console.print("[yellow]Invalid number. No changes made.[/yellow]")
    return config


def _change_filename_format(config: Config) -> Config:
    """Change the filename format setting."""
    console.print(f"\n[cyan]Current format:[/cyan] {config.filename_format}")
    console.print(
        "[dim]Placeholders: {{YYYY}}, {{MM}}, {{DD}}, {{HH}}, {{MM}}, {{SS}}[/dim]"
    )
    console.print(
        "[dim]Example: recording_{{YYYY}}-{{MM}}-{{DD}}_{{HH}}-{{MM}}-{{SS}}[/dim]"
    )

    fmt = Prompt.ask("Enter filename format", default=config.filename_format)
    fmt = fmt.strip()
    if fmt:
        config.filename_format = fmt
        save_config(config)
        console.print(f"[green]Filename format set to '{config.filename_format}'.[/green]")
    else:
        console.print("[yellow]Invalid format. No changes made.[/yellow]")
    return config


def _reset_settings() -> Config:
    """Reset all settings to defaults."""
    config = reset_config()
    console.print("[green]All settings have been reset to defaults.[/green]")
    import time
    time.sleep(1)
    return config

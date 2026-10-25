"""Menu display and navigation for RecCLI."""

import os
import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from audio import AudioRecorder
from config import Config, load_config, save_config
from recorder import ScreenRecorder
from settings import settings_menu
from utils import (
    check_ffmpeg,
    clear_screen,
    ensure_output_folder,
    format_duration,
    format_file_size,
    generate_filename,
    open_folder,
    read_key,
)

console = Console()


def display_main_menu(config: Config) -> None:
    """Display the main menu with current settings."""
    clear_screen()

    menu_text = (
        "[bold cyan]RecCLI[/bold cyan]\n"
        "\n"
        "  [white]1.[/white] Screen Recording\n"
        "  [white]2.[/white] Audio Recording\n"
        "  [white]3.[/white] Settings\n"
        "  [white]4.[/white] Exit\n"
        "\n"
        "[dim]─────────────────────────────[/dim]\n"
        "[bold]Current Settings[/bold]\n"
        "\n"
        f"  FPS      : [green]{config.fps}[/green]\n"
        f"  Quality  : [green]{config.quality.capitalize()}[/green]\n"
        f"  Output   : [green]{config.output_folder}/[/green]\n"
    )

    console.print(Panel(menu_text, border_style="bright_blue", width=40))


def display_screen_menu() -> str:
    """Display screen recording options. Returns the user's choice."""
    menu_text = (
        "[bold cyan]Screen Recording[/bold cyan]\n"
        "\n"
        "  [white]1.[/white] Screen Only\n"
        "  [white]2.[/white] Screen + System Audio\n"
        "  [white]3.[/white] Screen + System Audio + Microphone\n"
        "  [white]4.[/white] Back\n"
    )
    console.print(Panel(menu_text, border_style="bright_blue"))
    return Prompt.ask("Select an option", choices=["1", "2", "3", "4"], default="4")


def display_audio_menu() -> str:
    """Display audio recording options. Returns the user's choice."""
    menu_text = (
        "[bold cyan]Audio Recording[/bold cyan]\n"
        "\n"
        "  [white]1.[/white] System Audio\n"
        "  [white]2.[/white] Microphone\n"
        "  [white]3.[/white] System + Microphone\n"
        "  [white]4.[/white] Back\n"
    )
    console.print(Panel(menu_text, border_style="bright_blue"))
    return Prompt.ask("Select an option", choices=["1", "2", "3", "4"], default="4")


def countdown_timer(seconds: int) -> None:
    """Display a countdown before recording starts."""
    if seconds <= 0:
        return

    for i in range(seconds, 0, -1):
        clear_screen()
        console.print(
            Panel(
                f"[bold yellow]Recording starts in [white]{i}[/white]...[/bold yellow]",
                border_style="yellow",
            )
        )
        time.sleep(1)


def recording_screen(
    output_path: str,
    is_video: bool = True,
) -> tuple[bool, bool]:
    """Display the live recording status screen.

    Handles keyboard input for Pause (P) and Stop (S).
    Returns (should_pause, should_stop) — but this function is called
    in a loop from the recording handler.
    """
    # This is handled within the recording flow directly
    pass


def handle_screen_recording(config: Config) -> None:
    """Handle the screen recording flow."""
    clear_screen()
    choice = display_screen_menu()

    if choice == "4":
        return

    record_system_audio = choice in ("2", "3")
    record_mic = choice == "3"

    # Prepare output
    output_folder = ensure_output_folder(config.output_folder)
    filename = generate_filename(config.filename_format, "mp4")
    output_path = str(output_folder / filename)

    # Create recorder
    recorder = ScreenRecorder(
        config=config,
        output_path=output_path,
        record_system_audio=record_system_audio,
        record_mic=record_mic,
    )

    # Initialize
    console.print("[cyan]Initializing...[/cyan]")
    if not recorder.initialize():
        console.print("[red]Failed to initialize recorder.[/red]")
        Prompt.ask("\nPress Enter to continue")
        return

    # Countdown
    countdown_timer(config.countdown)

    # Start recording
    if not recorder.start():
        console.print("[red]Failed to start recording.[/red]")
        Prompt.ask("\nPress Enter to continue")
        return

    # Live recording display
    _live_recording_loop(recorder, output_path, is_video=True)


def handle_audio_recording(config: Config) -> None:
    """Handle the audio recording flow."""
    clear_screen()
    choice = display_audio_menu()

    if choice == "4":
        return

    record_system = choice in ("1", "3")
    record_mic = choice in ("2", "3")

    # Prepare output
    output_folder = ensure_output_folder(config.output_folder)
    filename = generate_filename(config.filename_format, "mp3")
    output_path = str(output_folder / filename)

    # Create audio recorder
    audio_rec = AudioRecorder(
        output_path=output_path,
        record_system=record_system,
        record_mic=record_mic,
    )

    # Initialize
    console.print("[cyan]Initializing audio...[/cyan]")
    if not audio_rec.initialize():
        console.print("[red]Failed to initialize audio recorder.[/red]")
        Prompt.ask("\nPress Enter to continue")
        return

    # Countdown
    countdown_timer(config.countdown)

    # Start recording
    if not audio_rec.start():
        console.print("[red]Failed to start audio recording.[/red]")
        Prompt.ask("\nPress Enter to continue")
        return

    # Live recording display (using a simple wrapper)
    _live_audio_loop(audio_rec, output_path)


def _live_recording_loop(
    recorder: ScreenRecorder,
    output_path: str,
    is_video: bool = True,
) -> None:
    """Display live recording status and handle P/S key input."""
    clear_screen()

    try:
        while recorder.is_recording:
            # Build status display
            elapsed = recorder.elapsed_time
            paused = recorder.is_paused

            # Check file size
            file_size = 0
            try:
                p = Path(output_path)
                if p.exists():
                    file_size = p.stat().st_size
                else:
                    # Check video-only path
                    vo = Path(output_path.replace(".mp4", "_video_only.mp4"))
                    if vo.exists():
                        file_size = vo.stat().st_size
            except OSError:
                pass

            status_icon = "[bold yellow]⏸  Paused[/bold yellow]" if paused else "[bold red]●  Recording[/bold red]"

            status_text = (
                f"{status_icon}\n"
                "\n"
                f"  [bold]Elapsed Time[/bold]\n"
                f"  [white]{format_duration(elapsed)}[/white]\n"
                "\n"
                f"  [bold]File Size[/bold]\n"
                f"  [white]{format_file_size(file_size)}[/white]\n"
                "\n"
                f"  [bold]Output[/bold]\n"
                f"  [dim]{output_path}[/dim]\n"
                "\n"
                "[dim]─────────────────────────────[/dim]\n"
                "  [cyan]P[/cyan] = Pause    [cyan]S[/cyan] = Stop\n"
            )

            clear_screen()
            console.print(Panel(status_text, border_style="red" if not paused else "yellow"))

            # Check for keyboard input without blocking on this platform.
            start_wait = time.time()
            while time.time() - start_wait < 0.5:
                key = read_key(0.05)
                if key == "p":
                    recorder.pause()
                elif key == "s":
                    clear_screen()
                    console.print("[cyan]Stopping and saving...[/cyan]")
                    final_path = recorder.stop()
                    _show_save_result(final_path, output_path)
                    return

    except KeyboardInterrupt:
        clear_screen()
        console.print("[cyan]Stopping and saving...[/cyan]")
        final_path = recorder.stop()
        _show_save_result(final_path, output_path)


def _live_audio_loop(
    audio_rec: AudioRecorder,
    output_path: str,
) -> None:
    """Display live audio recording status and handle P/S key input."""
    clear_screen()
    start_time = time.time()
    pause_offset = 0.0
    pause_start = 0.0

    try:
        while True:
            paused = audio_rec.is_paused

            if paused:
                elapsed = pause_start - start_time - pause_offset
            else:
                elapsed = time.time() - start_time - pause_offset

            status_icon = "[bold yellow]⏸  Paused[/bold yellow]" if paused else "[bold red]●  Recording[/bold red]"

            status_text = (
                f"{status_icon}\n"
                "\n"
                f"  [bold]Elapsed Time[/bold]\n"
                f"  [white]{format_duration(elapsed)}[/white]\n"
                "\n"
                f"  [bold]Output[/bold]\n"
                f"  [dim]{output_path}[/dim]\n"
                "\n"
                "[dim]─────────────────────────────[/dim]\n"
                "  [cyan]P[/cyan] = Pause    [cyan]S[/cyan] = Stop\n"
            )

            clear_screen()
            console.print(Panel(status_text, border_style="red" if not paused else "yellow"))

            # Check for keyboard input
            start_wait = time.time()
            while time.time() - start_wait < 0.5:
                key = read_key(0.05)
                if key == "p":
                    if not paused:
                        pause_start = time.time()
                    else:
                        pause_offset += time.time() - pause_start
                    audio_rec.pause()
                elif key == "s":
                    clear_screen()
                    console.print("[cyan]Stopping and saving...[/cyan]")
                    final_path = audio_rec.stop()
                    _show_save_result(final_path, output_path)
                    return

    except KeyboardInterrupt:
        clear_screen()
        console.print("[cyan]Stopping and saving...[/cyan]")
        final_path = audio_rec.stop()
        _show_save_result(final_path, output_path)


def _show_save_result(
    final_path: Optional[str],
    expected_path: str,
) -> None:
    """Display the post-recording result screen."""
    clear_screen()

    actual_path = final_path or expected_path

    if final_path and Path(final_path).is_file():
        actual_path = _prompt_recording_name(Path(final_path))

    if final_path and Path(final_path).exists():
        file_size = format_file_size(Path(final_path).stat().st_size)
        result_text = (
            "[bold green]Recording Saved Successfully[/bold green]\n"
            "\n"
            f"  [bold]Location[/bold]\n"
            f"  [white]{actual_path}[/white]\n"
            "\n"
            f"  [bold]File Size[/bold]\n"
            f"  [white]{file_size}[/white]\n"
            "\n"
            "  [white]1.[/white] Open Output Folder\n"
            "  [white]2.[/white] Return to Main Menu\n"
        )
    else:
        result_text = (
            "[bold yellow]Recording may not have saved correctly.[/bold yellow]\n"
            "\n"
            f"  [bold]Expected Location[/bold]\n"
            f"  [white]{expected_path}[/white]\n"
            "\n"
            "  [white]1.[/white] Open Output Folder\n"
            "  [white]2.[/white] Return to Main Menu\n"
        )

    console.print(Panel(result_text, border_style="green"))

    choice = Prompt.ask("Select an option", choices=["1", "2"], default="2")

    if choice == "1":
        folder = str(Path(actual_path).parent)
        open_folder(folder)


def _prompt_recording_name(path: Path) -> str:
    """Let the user rename the completed recording without overwriting files."""
    requested = Prompt.ask(
        "Name this recording (press Enter to keep the current name)",
        default=path.stem,
    ).strip()
    # Remove separators, control characters, and characters rejected by common
    # filesystems while preserving useful Unicode names.
    safe_name = "".join(
        "_" if ch in '<>:"/\\|?*' or ord(ch) < 32 else ch
        for ch in requested
    ).strip(" .")
    if not safe_name or safe_name == path.stem:
        return str(path)

    destination = path.with_name(f"{safe_name}{path.suffix}")
    counter = 2
    while destination.exists():
        destination = path.with_name(f"{safe_name} ({counter}){path.suffix}")
        counter += 1
    try:
        path.rename(destination)
        return str(destination)
    except OSError as e:
        console.print(f"[yellow]Could not rename recording: {e}[/yellow]")
        return str(path)


def run() -> None:
    """Main application loop."""
    # Check FFmpeg
    if not check_ffmpeg():
        console.print(
            Panel(
                "[bold red]FFmpeg not found![/bold red]\n\n"
                "RecCLI requires FFmpeg to record.\n"
                "Please install FFmpeg and add it to your system PATH.\n\n"
                "[dim]Download: https://ffmpeg.org/download.html[/dim]",
                border_style="red",
            )
        )
        sys.exit(1)

    # Load configuration
    config = load_config()

    # Ensure output folder exists
    ensure_output_folder(config.output_folder)

    while True:
        try:
            display_main_menu(config)
            choice = Prompt.ask(
                "Select an option",
                choices=["1", "2", "3", "4"],
                default="4",
            )

            if choice == "1":
                handle_screen_recording(config)
            elif choice == "2":
                handle_audio_recording(config)
            elif choice == "3":
                config = settings_menu(config)
            elif choice == "4":
                clear_screen()
                console.print("[bold cyan]Goodbye![/bold cyan]")
                sys.exit(0)

        except KeyboardInterrupt:
            console.print("\n[yellow]Use option 4 to exit.[/yellow]")
            time.sleep(1)
        except Exception as e:
            console.print(f"\n[red]Unexpected error: {e}[/red]")
            console.print("[yellow]Returning to main menu...[/yellow]")
            time.sleep(2)

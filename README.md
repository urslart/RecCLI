# RecCLI

A lightweight, modern command-line screen and audio recorder for Windows and Linux.

## Features

- **Screen Recording** — Capture your entire screen as MP4
- **Audio Recording** — Record system audio and/or microphone as MP3
- **Screen + Audio** — Record screen with system audio and microphone
- **Live Status** — Real-time elapsed time and file size during recording
- **Pause/Resume** — Pause and resume recordings on the fly
- **Configurable** — FPS, quality, output folder, countdown, filename format
- **Lightweight** — No GUI, no bloat — runs entirely in the terminal

## Requirements

- Python 3.10+
- Windows 10/11 or Linux (Wayland and X11)
- [FFmpeg](https://ffmpeg.org/) (must be on your system PATH)
- On Wayland: `wf-recorder` and a wlroots compositor such as Hyprland
- On Linux audio: PipeWire or PulseAudio with an output monitor source

## Installation

Clone the repository and use the installer for your operating system.

### Linux

 clone and install:

```bash
git clone https://github.com/urslart/RecCLI.git
cd RecCLI
./install.sh
```

The installer creates a private Python environment and installs the `reccli`
command for your user; it does not need root access.

Before running the installer, install Python 3 with its `venv` support, Git, and
FFmpeg using your distribution's package manager. For Hyprland/Wayland, also
install `wf-recorder`. For Linux system audio, make sure PipeWire or PulseAudio
is running and that `pactl` and `parec` are available. Package names differ
between distributions; the installer reports missing tools it can detect.

On CachyOS/Arch Linux, the system tools can be installed with:

```bash
sudo pacman -S --needed git python python-pip ffmpeg wf-recorder pipewire pipewire-pulse wireplumber portaudio
```

For a Hyprland session, make sure PipeWire, `pipewire-pulse`, and WirePlumber
are running. Wayland screen capture uses `wf-recorder`; X11 and Windows use MSS.
Linux system audio records directly from the current default speaker's `.monitor`
source through PipeWire's PulseAudio compatibility interface (`parec`/`pactl`).

The installer puts a private Python environment in
`~/.local/share/reccli/venv` and the `reccli` command in `~/.local/bin`.
If `~/.local/bin` is not already on your PATH, add it using the command printed
by the installer. Then launch RecCLI from any folder:

```bash
reccli
```

Settings are stored in `~/.config/reccli/config.json` and new recordings go to
`~/Videos/RecCLI`. The existing project-local settings are migrated on first run.
To update a clone installation, run `git pull` inside the cloned folder, then
rerun `./install.sh` to refresh dependencies. The code changes take effect from
the clone immediately because the Python environment installs the project in
editable mode.

### Windows 10/11

Install Python 3.10 or newer (enable the Python launcher or add Python to PATH),
Git, and [FFmpeg](https://ffmpeg.org/). Then open PowerShell and run:

```powershell
git clone https://github.com/urslart/RecCLI.git
cd RecCLI
.\install.ps1
```

The Windows installer creates a private environment under
`%LOCALAPPDATA%\RecCLI`, installs a `reccli` command, and adds its launcher
folder to your user PATH. Open a new terminal after installation, then run:

```powershell
reccli
```

Windows uses FFmpeg from PATH for recording. RecCLI uses FFmpeg's Desktop
Duplication and Media Foundation hardware-encoding path when available, then
falls back to FFmpeg desktop capture before using software capture.
New Windows configurations default to 30 FPS to reduce load; you can choose a
higher rate in Settings. WASAPI loopback records the active speaker output;
the Windows installer also installs the loopback audio dependency. To update,
run `git pull` in the cloned folder and rerun `install.ps1`.
Windows settings are stored in `%APPDATA%\reccli\config.json`, and recordings
go to your `Videos\RecCLI` folder by default.

## Usage

```bash
reccli
```

When running directly from a clone without installing the command, use
`python3 main.py` from the project folder.

The application will display a menu:

```
╭──────────────────────────────────────╮
│ RecCLI                               │
│                                      │
│   1. Screen Recording                │
│   2. Audio Recording                 │
│   3. Settings                        │
│   4. Exit                            │
│                                      │
│ ───────────────────────────────      │
│ Current Settings                     │
│                                      │
│   FPS      : 60                      │
│   Quality  : High                    │
│   Output   : ~/Videos/RecCLI/       │
╰──────────────────────────────────────╯
```

### Screen Recording

Choose from:
- Screen only (no audio)
- Screen + System Audio
- Screen + System Audio + Microphone

### Audio Recording

Choose from:
- System Audio only
- Microphone only
- System Audio + Microphone

All audio recordings are saved as MP3.

### During Recording

```
╭──────────────────────────────────────╮
│ ●  Recording                         │
│                                      │
│   Elapsed Time                       │
│   00:05:31                           │
│                                      │
│   File Size                          │
│   182 MB                             │
│                                      │
│   Output                             │
│   ~/Videos/RecCLI/recording_...mp4   │
│                                      │
│ ───────────────────────────────      │
│   P = Pause    S = Stop              │
╰──────────────────────────────────────╯
```

- Press **P** to pause/resume
- Press **S** to stop and save
- After saving, enter a name for the recording or press Enter to keep the timestamp name

## Settings

Configurable through the Settings menu:

| Setting          | Default                                        | Options               |
|------------------|------------------------------------------------|-----------------------|
| FPS              | 60                                             | 15, 24, 30, 60       |
| Video Quality    | High                                           | Low, Medium, High     |
| Output Folder    | ~/Videos/RecCLI/                               | Any valid path        |
| Countdown        | 3 seconds                                      | 0–10 seconds          |
| Filename Format  | recording_{YYYY}-{MM}-{DD}_{HH}-{MM}-{SS}     | Custom pattern        |

Settings are stored in the per-user config folder and persist between sessions.

## Project Structure

```
reccli/
├── main.py            # Entry point
├── menu.py            # Menu display and navigation
├── recorder.py        # Screen recording (MSS + FFmpeg)
├── audio.py           # Audio recording (SoundDevice + SoundFile)
├── settings.py        # Settings menu
├── config.py          # Configuration management
├── utils.py           # Utility functions
├── pyproject.toml     # Python package and `reccli` command metadata
├── requirements.txt   # Python dependencies
├── install.sh         # User-level Linux installer
├── install.ps1        # User-level Windows installer
├── README.md          # This file
├── LICENSE            # MIT license
└── .gitignore         # Excludes local recordings and build artifacts
```

## How It Works

1. **Screen Capture**: Uses FFmpeg Desktop Duplication with Media Foundation hardware encoding on supported Windows FFmpeg builds, and [MSS](https://python-mss.readthedocs.io/) as a Windows fallback and on X11. On Wayland it uses `wf-recorder` to capture through the compositor's screencopy protocol.

2. **Video Encoding**: FFmpeg produces H.264 MP4. Windows uses Media Foundation quality settings when supported; the software paths use configurable CRF and presets.

3. **Audio Capture**: Uses [PyAudioWPatch](https://pypi.org/project/PyAudioWPatch/) to select the active WASAPI speaker loopback on Windows, and SoundDevice for microphone input. On Linux, it records the default PipeWire monitor through the PulseAudio compatibility tools. Audio is converted to MP3 with FFmpeg.

4. **Audio/Video Muxing**: When recording screen + audio, the video and audio are recorded separately and then muxed together by FFmpeg.

5. **Terminal UI**: Built with [Rich](https://rich.readthedocs.io/) for a clean, modern terminal interface.

## License

MIT License

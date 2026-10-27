"""Screen recording module for RecCLI.

Captures the screen using MSS and encodes video with FFmpeg.
Optionally records audio alongside video.

The capture loop uses wall-clock timing rather than assuming that every
captured frame took exactly 1/FPS seconds to produce. This prevents the
recorded video from becoming shorter than the real recording when MSS or
FFmpeg temporarily stalls.
"""

import subprocess
import threading
import time
import os
import shutil
import signal
from pathlib import Path
from typing import Optional

import mss
import numpy as np
from rich.console import Console

from audio import AudioRecorder
from config import Config
from utils import get_quality_crf, get_quality_preset

console = Console()


class ScreenRecorder:
    """Records the primary screen to an MP4 file using MSS + FFmpeg."""

    def __init__(
        self,
        config: Config,
        output_path: str,
        record_system_audio: bool = False,
        record_mic: bool = False,
    ) -> None:
        self.config = config
        self.output_path = output_path
        self.record_system_audio = record_system_audio
        self.record_mic = record_mic

        self._is_recording = False
        self._is_paused = False
        self._thread: Optional[threading.Thread] = None
        self._ffmpeg_process: Optional[subprocess.Popen] = None
        self._audio_recorder: Optional[AudioRecorder] = None
        self._start_time: float = 0.0
        self._pause_offset: float = 0.0
        self._pause_start: float = 0.0
        self._lock = threading.Lock()
        self._capture_start_time: float = 0.0
        self._frames_written: int = 0
        self._video_only_path: str = output_path
        self._wayland_process: Optional[subprocess.Popen] = None
        self._wayland_capture = os.name != "nt" and bool(os.environ.get("WAYLAND_DISPLAY"))
        self._windows_ddagrab = False
        self._windows_direct_capture = False
        self._windows_h264_mf = False
        self._windows_gdigrab = False
        self._windows_video_started_at: Optional[float] = None
        self._audio_offset: float = 0.0

    def _audio_input_args(self, audio_path: str) -> list[str]:
        """Put separately captured audio at its actual point on the video timeline."""
        if self._audio_offset > 0:
            return ["-itsoffset", f"{self._audio_offset:.6f}", "-i", audio_path]
        if self._audio_offset < 0:
            return ["-ss", f"{-self._audio_offset:.6f}", "-i", audio_path]
        return ["-i", audio_path]

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def elapsed_time(self) -> float:
        """Return elapsed recording time in seconds, excluding pauses."""
        if not self._is_recording:
            return 0.0
        if self._is_paused:
            return self._pause_start - self._start_time - self._pause_offset
        return time.perf_counter() - self._start_time - self._pause_offset

    def _get_audio_output_path(self) -> str:
        """Generate a temporary audio file path alongside the video."""
        base = Path(self.output_path).with_suffix("")
        return str(base) + "_audio.mp3"

    def initialize(self) -> bool:
        """Initialize recording components. Returns True on success."""
        if self._wayland_capture:
            if not shutil.which("wf-recorder"):
                console.print("[red]Wayland screen capture needs wf-recorder (install it with your package manager).[/red]")
                return False
            if shutil.which("ffmpeg") is None:
                console.print("[red]FFmpeg was not found on PATH.[/red]")
                return False
            # wf-recorder captures through the compositor's screencopy protocol,
            # which works in wlroots compositors such as Hyprland.
            if self.record_system_audio or self.record_mic:
                self._audio_recorder = AudioRecorder(
                    output_path=self._get_audio_output_path(),
                    record_system=self.record_system_audio,
                    record_mic=self.record_mic,
                )
                if not self._audio_recorder.initialize():
                    return False
            return True

        if os.name == "nt" and shutil.which("ffmpeg"):
            # Desktop Duplication keeps frames on the GPU instead of copying
            # every full-screen frame through Python.
            try:
                filters_result = subprocess.run(
                    ["ffmpeg", "-hide_banner", "-filters"],
                    capture_output=True, text=True, timeout=10,
                )
                encoders_result = subprocess.run(
                    ["ffmpeg", "-hide_banner", "-encoders"],
                    capture_output=True, text=True, timeout=10,
                )
                devices_result = subprocess.run(
                    ["ffmpeg", "-hide_banner", "-devices"],
                    capture_output=True, text=True, timeout=10,
                )
                filters = filters_result.stdout + filters_result.stderr
                encoders = encoders_result.stdout + encoders_result.stderr
                devices = devices_result.stdout + devices_result.stderr
                self._windows_h264_mf = " h264_mf " in encoders
                self._windows_ddagrab = " ddagrab " in filters and self._windows_h264_mf
                self._windows_gdigrab = " gdigrab " in devices
            except (OSError, subprocess.SubprocessError):
                self._windows_ddagrab = False
            if self._windows_ddagrab:
                console.print("[dim]Windows capture: Desktop Duplication + Media Foundation[/dim]")

        if self.record_system_audio or self.record_mic:
            audio_path = self._get_audio_output_path()
            self._audio_recorder = AudioRecorder(
                output_path=audio_path,
                record_system=self.record_system_audio,
                record_mic=self.record_mic,
            )
            if not self._audio_recorder.initialize():
                return False

        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                if monitor["width"] <= 0 or monitor["height"] <= 0:
                    console.print("[red]Invalid monitor dimensions.[/red]")
                    return False
        except Exception as e:
            console.print(f"[red]Screen capture initialization failed: {e}[/red]")
            return False

        return True

    def start(self) -> bool:
        """Start screen and optional audio recording."""
        if self._wayland_capture:
            if self._audio_recorder:
                self._video_only_path = str(Path(self.output_path).with_name(
                    Path(self.output_path).stem + "_video_only.mp4"
                ))
            else:
                self._video_only_path = self.output_path
            cmd = [
                "wf-recorder", "-y", "-f", self._video_only_path,
                "-r", str(self.config.fps), "-c", "libx264",
                "-p", f"crf={get_quality_crf(self.config.quality)}",
                # Keep the compositor-driven capture path light enough for
                # real-time 1080p recording, especially at 60 fps.
                "-p", "preset=ultrafast",
            ]
            try:
                self._wayland_process = subprocess.Popen(
                    cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                video_started_at = time.perf_counter()
                time.sleep(0.25)
                if self._wayland_process.poll() is not None:
                    console.print("[red]wf-recorder could not start. Check compositor capture permissions and FFmpeg codecs.[/red]")
                    self._wayland_process = None
                    return False
                if self._audio_recorder and not self._audio_recorder.start():
                    console.print("[yellow]Warning: Audio recording failed to start.[/yellow]")
                if self._audio_recorder and self._audio_recorder.started_at is not None:
                    self._audio_offset = self._audio_recorder.started_at - video_started_at
                self._start_time = time.perf_counter()
                self._pause_offset = 0.0
                self._is_paused = False
                self._is_recording = True
                return True
            except (OSError, subprocess.SubprocessError) as e:
                console.print(f"[red]Error starting Wayland recording: {e}[/red]")
                return False
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                width = monitor["width"]
                height = monitor["height"]

            width = width if width % 2 == 0 else width - 1
            height = height if height % 2 == 0 else height - 1

            crf = get_quality_crf(self.config.quality)
            preset = get_quality_preset(self.config.quality)
            if os.name == "nt":
                # Keep the software fallback responsive on Windows CPUs.
                preset = "ultrafast"

            self._video_only_path = (
                str(Path(self.output_path).with_name(Path(self.output_path).stem + "_video_only.mp4"))
                if self._audio_recorder else self.output_path
            )

            if self._windows_ddagrab:
                quality = {"low": 60, "medium": 78, "high": 90}.get(
                    self.config.quality.lower(), 78
                )
                ffmpeg_cmd = [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i",
                    f"ddagrab=framerate={self.config.fps}:draw_mouse=1",
                    "-an", "-c:v", "h264_mf", "-hw_encoding", "1",
                    "-quality", str(quality), "-pix_fmt", "nv12",
                    "-fps_mode", "cfr", self._video_only_path,
                ]
                try:
                    self._ffmpeg_process = subprocess.Popen(
                        ffmpeg_cmd, stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    self._windows_video_started_at = time.perf_counter()
                    time.sleep(0.5)
                    if self._ffmpeg_process.poll() is None:
                        self._windows_direct_capture = True
                        console.print("[dim]Windows capture: Desktop Duplication + Media Foundation[/dim]")
                    else:
                        self._ffmpeg_process = None
                        self._windows_video_started_at = None
                        console.print(
                            "[yellow]Windows hardware capture could not start; "
                            "falling back to software capture.[/yellow]"
                        )
                except (OSError, subprocess.SubprocessError):
                    self._ffmpeg_process = None

            # GDI capture is supported by most Windows FFmpeg builds. It
            # captures and encodes in FFmpeg directly, avoiding Python frame
            # copies even when Desktop Duplication is unavailable.
            if not self._windows_direct_capture and self._windows_gdigrab:
                ffmpeg_cmd = [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "gdigrab", "-framerate", str(self.config.fps),
                    "-draw_mouse", "1", "-i", "desktop",
                ]
                if self._windows_h264_mf:
                    quality = {"low": 60, "medium": 78, "high": 90}.get(
                        self.config.quality.lower(), 78
                    )
                    ffmpeg_cmd += [
                        "-c:v", "h264_mf", "-hw_encoding", "1",
                        "-quality", str(quality), "-pix_fmt", "nv12",
                    ]
                else:
                    ffmpeg_cmd += [
                        "-c:v", "libx264", "-preset", "ultrafast",
                        "-crf", str(crf), "-pix_fmt", "yuv420p",
                    ]
                ffmpeg_cmd += ["-fps_mode", "cfr", self._video_only_path]
                try:
                    self._ffmpeg_process = subprocess.Popen(
                        ffmpeg_cmd, stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    self._windows_video_started_at = time.perf_counter()
                    time.sleep(0.5)
                    self._windows_direct_capture = self._ffmpeg_process.poll() is None
                    if not self._windows_direct_capture:
                        self._ffmpeg_process = None
                        self._windows_video_started_at = None
                    else:
                        console.print("[dim]Windows capture: FFmpeg desktop capture[/dim]")
                except (OSError, subprocess.SubprocessError):
                    self._ffmpeg_process = None
                    self._windows_video_started_at = None

            # Rawvideo is intentionally kept CFR, but the capture loop below
            # duplicates frames when the real-time clock gets ahead of the
            # number of frames written. Therefore the output duration follows
            # wall-clock time instead of the speed of the capture/encode loop.
            ffmpeg_cmd = [
                "ffmpeg",
                "-y",
                "-f", "rawvideo",
                "-vcodec", "rawvideo",
                "-pix_fmt", "bgra",
                "-s", f"{width}x{height}",
                "-framerate", str(self.config.fps),
                "-i", "-",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", preset,
                "-crf", str(crf),
                "-fps_mode", "cfr",
                self._video_only_path,
            ]

            if not self._windows_direct_capture:
                self._ffmpeg_process = subprocess.Popen(
                    ffmpeg_cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            # Start the audio streams before the video capture thread, then
            # establish the common recording clock immediately afterward.
            if self._audio_recorder:
                if not self._audio_recorder.start():
                    console.print(
                        "[yellow]Warning: Audio recording failed to start.[/yellow]"
                    )

            start = time.perf_counter()
            if self._audio_recorder and self._audio_recorder.started_at is not None:
                # Native Windows capture starts when FFmpeg launches, before
                # the startup probe delay. Offset audio from that actual origin.
                video_start = (
                    self._windows_video_started_at
                    if self._windows_direct_capture and self._windows_video_started_at
                    else start
                )
                self._audio_offset = self._audio_recorder.started_at - video_start
            self._start_time = start
            self._capture_start_time = start
            self._pause_offset = 0.0
            self._pause_start = 0.0
            self._frames_written = 0
            self._is_paused = False
            self._is_recording = True

            if not self._windows_direct_capture:
                self._thread = threading.Thread(
                    target=self._capture_loop,
                    args=(width, height),
                    daemon=True,
                )
                self._thread.start()
            return True

        except FileNotFoundError:
            console.print("[red]FFmpeg not found. Please install FFmpeg.[/red]")
            return False
        except Exception as e:
            console.print(f"[red]Error starting screen recording: {e}[/red]")
            return False

    def _write_frame(self, frame_data: bytes, count: int) -> None:
        """Write a frame to FFmpeg, repeated count times."""
        if count <= 0:
            return
        process = self._ffmpeg_process
        if not process or not process.stdin:
            return
        for _ in range(count):
            if not self._is_recording:
                break
            try:
                process.stdin.write(frame_data)
                self._frames_written += 1
            except (BrokenPipeError, OSError):
                self._is_recording = False
                break

    def _capture_loop(self, width: int, height: int) -> None:
        """Capture frames while keeping output duration tied to real time."""
        fps = max(1, int(self.config.fps))
        frame_interval = 1.0 / fps

        try:
            with mss.mss() as sct:
                monitor = {
                    "top": sct.monitors[1]["top"],
                    "left": sct.monitors[1]["left"],
                    "width": width,
                    "height": height,
                }

                next_capture_time = time.perf_counter()

                while self._is_recording:
                    if self._is_paused:
                        time.sleep(0.02)
                        next_capture_time = time.perf_counter()
                        continue

                    now = time.perf_counter()
                    if now < next_capture_time:
                        time.sleep(min(next_capture_time - now, 0.005))
                        continue

                    try:
                        img = sct.grab(monitor)
                        frame_data = img.raw
                    except Exception:
                        if not self._is_recording:
                            break
                        next_capture_time = time.perf_counter()
                        continue

                    # Calculate how many CFR frames should exist by this point
                    # in real time. If capture/encoding took longer than the
                    # target interval, duplicate the newest frame instead of
                    # silently losing several seconds from the output.
                    elapsed = time.perf_counter() - self._capture_start_time
                    expected_frames = max(1, int(elapsed * fps) + 1)
                    frames_to_write = expected_frames - self._frames_written
                    self._write_frame(frame_data, frames_to_write)

                    next_capture_time += frame_interval
                    if next_capture_time < time.perf_counter() - frame_interval:
                        next_capture_time = time.perf_counter()

        except Exception as e:
            if self._is_recording:
                console.print(f"[red]Capture error: {e}[/red]")

    def pause(self) -> None:
        """Toggle pause state and synchronize audio."""
        with self._lock:
            now = time.perf_counter()
            if self._is_paused:
                self._pause_offset += now - self._pause_start
                self._is_paused = False
                # Remove the paused interval from the wall-clock frame
                # timeline so pause/resume does not create a burst of
                # duplicated frames for the time spent paused.
                self._capture_start_time += now - self._pause_start
            else:
                self._pause_start = now
                self._is_paused = True

            if self._audio_recorder:
                self._audio_recorder.pause()
            if self._windows_direct_capture and self._ffmpeg_process and self._ffmpeg_process.stdin:
                try:
                    self._ffmpeg_process.stdin.write(b"p")
                    self._ffmpeg_process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
            if self._wayland_process and self._wayland_process.poll() is None:
                try:
                    os.kill(self._wayland_process.pid, signal.SIGCONT if not self._is_paused else signal.SIGSTOP)
                except OSError:
                    pass

    def stop(self) -> Optional[str]:
        """Stop recording and finalize the output file."""
        self._is_recording = False

        if self._wayland_process:
            process = self._wayland_process
            if process.poll() is None:
                try:
                    # Resume before interrupting so a paused process can finalize its MP4.
                    os.kill(process.pid, signal.SIGCONT)
                    process.send_signal(signal.SIGINT)
                    process.wait(timeout=30)
                except (OSError, subprocess.TimeoutExpired):
                    process.kill()
                    process.wait()
            self._wayland_process = None

            audio_path: Optional[str] = None
            if self._audio_recorder:
                if self._audio_recorder.is_paused:
                    self._audio_recorder.pause()
                audio_path = self._audio_recorder.stop()
            if audio_path and Path(audio_path).exists() and Path(self._video_only_path).exists():
                duration = self._get_video_duration(self._video_only_path)
                cmd = ["ffmpeg", "-y", "-i", self._video_only_path,
                       *self._audio_input_args(audio_path),
                       "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                       "-c:a", "aac", "-b:a", "192k", "-af", "apad",
                       "-movflags", "+faststart"]
                if duration:
                    cmd += ["-t", duration]
                cmd.append(self.output_path)
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if result.returncode == 0:
                    for temp in (self._video_only_path, audio_path):
                        try:
                            Path(temp).unlink()
                        except OSError:
                            pass
                    return self.output_path
                console.print(f"[yellow]Muxing warning: {result.stderr[-500:]}[/yellow]")
                return self._video_only_path
            return self._video_only_path if Path(self._video_only_path).exists() else self.output_path

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

        if self._ffmpeg_process and self._ffmpeg_process.stdin:
            try:
                if self._windows_direct_capture:
                    if self._is_paused:
                        self._ffmpeg_process.stdin.write(b"p")
                    self._ffmpeg_process.stdin.write(b"q")
                    self._ffmpeg_process.stdin.flush()
                self._ffmpeg_process.stdin.close()
            except Exception:
                pass

        if self._ffmpeg_process:
            try:
                self._ffmpeg_process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                self._ffmpeg_process.kill()
            self._ffmpeg_process = None
        self._windows_direct_capture = False
        self._windows_video_started_at = None

        audio_path: Optional[str] = None
        if self._audio_recorder:
            # If the user stops while paused, resume first so the audio stream
            # is closed in a consistent state.
            if self._audio_recorder.is_paused:
                self._audio_recorder.pause()
            audio_path = self._audio_recorder.stop()

        if audio_path and Path(audio_path).exists() and Path(self._video_only_path).exists():
            video_only = self._video_only_path
            final_output = self.output_path

            try:
                # Do not use -shortest here. The video is now generated with
                # wall-clock duration; trimming to the shorter stream can
                # otherwise throw away the end of the recording.
                video_duration = self._get_video_duration(video_only)
                mux_cmd = [
                    "ffmpeg",
                    "-y",
                    "-i", video_only,
                    *self._audio_input_args(audio_path),
                    "-map", "0:v:0",
                    "-map", "1:a:0",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-af", "apad",
                    "-movflags", "+faststart",
                ]
                if video_duration is not None:
                    mux_cmd += ["-t", video_duration]
                mux_cmd.append(final_output)
                result = subprocess.run(
                    mux_cmd, capture_output=True, text=True, timeout=120
                )

                if result.returncode == 0:
                    for temp in (video_only, audio_path):
                        try:
                            Path(temp).unlink()
                        except OSError:
                            pass
                    return final_output

                console.print(
                    f"[yellow]Muxing warning: {result.stderr[-500:]}[/yellow]"
                )
                return video_only

            except Exception as e:
                console.print(f"[yellow]Muxing error: {e}[/yellow]")
                return video_only

        return self._video_only_path if Path(self._video_only_path).exists() else self.output_path

    @staticmethod
    def _get_video_duration(path: str) -> Optional[str]:
        """Read the final video duration using ffprobe."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    path,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            duration = result.stdout.strip()
            if duration:
                return duration
        except Exception:
            pass
        return None

"""Audio recording module for RecCLI.

Handles system audio (loopback) and microphone recording using
SoundDevice and SoundFile libraries.
"""

import threading
import time
import os
import signal
import shutil
import subprocess
import sys
import threading
import wave
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf
from rich.console import Console

console = Console()

# Audio settings
CHANNELS: int = 2
BLOCK_SIZE: int = 1024


def _get_pipewire_monitor() -> Optional[str]:
    """Return the monitor source for the current default PipeWire sink."""
    if not shutil.which("parec") or not shutil.which("pactl"):
        return None
    try:
        sink = subprocess.run(
            ["pactl", "get-default-sink"], capture_output=True, text=True,
            check=True, timeout=5,
        ).stdout.strip()
        sources = subprocess.run(
            ["pactl", "list", "short", "sources"], capture_output=True,
            text=True, check=True, timeout=5,
        ).stdout.splitlines()
        monitors = [line.split()[1] for line in sources
                    if len(line.split()) > 1 and line.split()[1].endswith(".monitor")]
        if sink:
            for name in monitors:
                if name == f"{sink}.monitor":
                    return name
        return monitors[0] if monitors else None
    except (OSError, subprocess.SubprocessError):
        return None


def get_loopback_device() -> Optional[dict]:
    """Find a system-output monitor device (WASAPI or PulseAudio/PipeWire).

    Returns the device info dict or None if not found.
    """
    try:
        devices = sd.query_devices()
        host_apis = sd.query_hostapis()

        # Linux exposes output monitors as input sources through PulseAudio,
        # which is also the compatibility interface used by PipeWire.
        for i, dev in enumerate(devices):
            api_name = host_apis[dev.get("hostapi", -1)].get("name", "").lower()
            name = dev.get("name", "").lower()
            is_monitor = "monitor" in name or "loopback" in name
            if dev.get("max_input_channels", 0) > 0 and is_monitor and (
                "wasapi" in api_name or "pulse" in api_name or "pipewire" in api_name
                or "monitor" in name or "loopback" in name
            ):
                return {**dev, "index": i}

        # Keep the original Windows fallback for drivers that omit "loopback"
        for i, dev in enumerate(devices):
            api_name = host_apis[dev.get("hostapi", -1)].get("name", "").lower()
            if "wasapi" in api_name and dev.get("max_input_channels", 0) > 0:
                return {**dev, "index": i}

    except Exception as e:
        console.print(f"[red]Error finding loopback device: {e}[/red]")

    return None


def get_microphone_device() -> Optional[dict]:
    """Find the default microphone input device.

    Returns the device info dict or None if not found.
    """
    try:
        default_input = sd.default.device[0]
        if default_input is not None and default_input >= 0:
            dev = sd.query_devices(default_input)
            return {**dev, "index": default_input}
    except Exception:
        pass

    # Fallback: find any input device
    try:
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) > 0:
                return {**dev, "index": i}
    except Exception as e:
        console.print(f"[red]Error finding microphone: {e}[/red]")

    return None


def _get_device_sample_rate(device: dict) -> int:
    """Get the native sample rate of a device.

    Always use the device's own default_samplerate to avoid
    PaErrorCode -9997 (Invalid sample rate) with WASAPI.
    """
    return int(device.get("default_samplerate", 48000))


class AudioRecorder:
    """Records audio from system loopback and/or microphone."""

    def __init__(
        self,
        output_path: str,
        record_system: bool = False,
        record_mic: bool = False,
    ) -> None:
        self.output_path = output_path
        self.record_system = record_system
        self.record_mic = record_mic

        self._is_recording = False
        self._is_paused = False
        self._lock = threading.Lock()
        self._frames: list[np.ndarray] = []
        self._mic_frames: list[np.ndarray] = []

        self._system_stream: Optional[sd.InputStream] = None
        self._mic_stream: Optional[sd.InputStream] = None
        self._system_device: Optional[dict] = None
        self._mic_device: Optional[dict] = None

        # Sample rates queried from each device
        self._system_sample_rate: int = 48000
        self._mic_sample_rate: int = 48000
        # The rate used for the final output file
        self._output_sample_rate: int = 48000
        self._pw_monitor: Optional[str] = None
        self._pw_process: Optional[subprocess.Popen] = None
        self._pw_wav_path = str(Path(output_path).with_suffix(".system.wav"))
        self._wasapi_wav_path = str(Path(output_path).with_suffix(".system.wav"))
        self._wasapi_manager = None
        self._wasapi_stream = None
        self._wasapi_wave = None
        self._wasapi_thread: Optional[threading.Thread] = None
        self._wasapi_stop = threading.Event()
        self._wasapi_channels = 2
        self._wasapi_sample_rate = 48000
        self._wasapi_chunk_size = 1024
        self._wasapi_error: Optional[Exception] = None
        self.started_at: Optional[float] = None

    def _system_callback(
        self, indata: np.ndarray, frames: int, time_info: any, status: any
    ) -> None:
        """Callback for system audio capture."""
        if self._is_paused:
            return
        with self._lock:
            self._frames.append(indata.copy())

    def _mic_callback(
        self, indata: np.ndarray, frames: int, time_info: any, status: any
    ) -> None:
        """Callback for microphone capture."""
        if self._is_paused:
            return
        with self._lock:
            # If recording both, mic frames are stored separately for mixing
            if self.record_system:
                self._mic_frames.append(indata.copy())
            else:
                self._frames.append(indata.copy())

    def initialize(self) -> bool:
        """Initialize audio devices. Returns True on success."""
        if self.record_system:
            if sys.platform.startswith("linux"):
                self._pw_monitor = _get_pipewire_monitor()
                if self._pw_monitor:
                    self._system_sample_rate = 48000
                    console.print(f"[dim]System audio monitor: {self._pw_monitor} @ 48000 Hz[/dim]")
                else:
                    console.print("[red]Could not find a PipeWire monitor source. Install/start PipeWire and ensure pactl and parec are available.[/red]")
                    return False
            elif os.name == "nt":
                try:
                    import pyaudiowpatch as pyaudio

                    self._wasapi_manager = pyaudio.PyAudio()
                    self._system_device = self._wasapi_manager.get_default_wasapi_loopback()
                    self._wasapi_sample_rate = int(self._system_device["defaultSampleRate"])
                    self._wasapi_channels = min(2, int(self._system_device["maxInputChannels"]))
                    if self._wasapi_channels < 1:
                        raise RuntimeError("the default speaker loopback has no input channels")
                    self._system_sample_rate = self._wasapi_sample_rate
                    console.print(
                        f"[dim]System audio loopback: {self._system_device['name']} "
                        f"@ {self._system_sample_rate} Hz[/dim]"
                    )
                except Exception as e:
                    if self._wasapi_manager is not None:
                        self._wasapi_manager.terminate()
                        self._wasapi_manager = None
                    console.print(f"[red]Could not initialize WASAPI speaker loopback: {e}[/red]")
                    console.print("[yellow]Check that Windows has an active output device and update RecCLI.[/yellow]")
                    return False
            else:
                self._system_device = get_loopback_device()
                if self._system_device is None:
                    console.print("[red]Could not find a system audio loopback device.[/red]")
                    console.print("[yellow]Tip: Ensure WASAPI loopback is available on your system.[/yellow]")
                    return False
                self._system_sample_rate = _get_device_sample_rate(self._system_device)
                console.print(
                    f"[dim]System audio device: {self._system_device.get('name', 'Unknown')} "
                    f"@ {self._system_sample_rate} Hz[/dim]"
                )

        if self.record_mic:
            self._mic_device = get_microphone_device()
            if self._mic_device is None:
                console.print("[red]Could not find a microphone device.[/red]")
                return False
            self._mic_sample_rate = _get_device_sample_rate(self._mic_device)
            console.print(
                f"[dim]Microphone device: {self._mic_device.get('name', 'Unknown')} "
                f"@ {self._mic_sample_rate} Hz[/dim]"
            )

        # Determine the output sample rate (use the system device rate if
        # available, otherwise use the mic rate)
        if self.record_system:
            self._output_sample_rate = self._system_sample_rate
        else:
            self._output_sample_rate = self._mic_sample_rate

        return True

    def start(self) -> bool:
        """Start audio recording. Returns True on success."""
        self._is_recording = True
        self._is_paused = False
        self._frames = []
        self._mic_frames = []
        self.started_at = None

        try:
            if self.record_system and self._pw_monitor:
                self._pw_process = subprocess.Popen(
                    ["parec", f"--device={self._pw_monitor}", "--file-format=wav",
                     "--rate=48000", "--channels=2", "--format=s16le", self._pw_wav_path],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.started_at = time.perf_counter()
                time.sleep(0.2)
                if self._pw_process.poll() is not None:
                    self._pw_process = None
                    raise RuntimeError("parec could not start on the monitor source")
            elif self.record_system and os.name == "nt" and self._wasapi_manager:
                import pyaudiowpatch as pyaudio

                self._wasapi_stop.clear()
                self._wasapi_error = None
                self._wasapi_wave = wave.open(self._wasapi_wav_path, "wb")
                self._wasapi_wave.setnchannels(self._wasapi_channels)
                self._wasapi_wave.setsampwidth(self._wasapi_manager.get_sample_size(pyaudio.paInt16))
                self._wasapi_wave.setframerate(self._system_sample_rate)
                self._wasapi_stream = self._wasapi_manager.open(
                    format=pyaudio.paInt16,
                    channels=self._wasapi_channels,
                    rate=self._system_sample_rate,
                    input=True,
                    input_device_index=self._system_device["index"],
                    frames_per_buffer=self._wasapi_chunk_size,
                )
                self.started_at = time.perf_counter()
                self._wasapi_thread = threading.Thread(
                    target=self._wasapi_read_loop, daemon=True
                )
                self._wasapi_thread.start()
            elif self.record_system and self._system_device:
                channels = min(
                    self._system_device.get("max_input_channels", 2),
                    CHANNELS,
                )
                self._system_stream = sd.InputStream(
                    samplerate=self._system_sample_rate,
                    blocksize=BLOCK_SIZE,
                    device=self._system_device["index"],
                    channels=channels,
                    callback=self._system_callback,
                    dtype="float32",
                )
                self._system_stream.start()
                self.started_at = time.perf_counter()

            if self.record_mic and self._mic_device:
                channels = min(
                    self._mic_device.get("max_input_channels", 1),
                    CHANNELS,
                )
                self._mic_stream = sd.InputStream(
                    samplerate=self._mic_sample_rate,
                    blocksize=BLOCK_SIZE,
                    device=self._mic_device["index"],
                    channels=channels,
                    callback=self._mic_callback,
                    dtype="float32",
                )
                self._mic_stream.start()
                if self.started_at is None:
                    self.started_at = time.perf_counter()

            return True

        except Exception as e:
            console.print(f"[red]Error starting audio recording: {e}[/red]")
            self.stop()
            return False

    def _wasapi_read_loop(self) -> None:
        """Read Windows speaker-loopback chunks and stream them to a WAV file."""
        try:
            while not self._wasapi_stop.is_set():
                data = self._wasapi_stream.read(
                    self._wasapi_chunk_size, exception_on_overflow=False
                )
                if not self._is_paused and data:
                    self._wasapi_wave.writeframesraw(data)
        except Exception as e:
            if not self._wasapi_stop.is_set():
                self._wasapi_error = e

    def _stop_wasapi(self) -> None:
        """Stop loopback reads and close the WAV and WASAPI resources."""
        self._wasapi_stop.set()
        if self._wasapi_stream is not None:
            try:
                if self._wasapi_stream.is_active():
                    self._wasapi_stream.stop_stream()
            except Exception:
                pass
        if self._wasapi_thread is not None:
            self._wasapi_thread.join(timeout=5)
            self._wasapi_thread = None
        if self._wasapi_stream is not None:
            try:
                self._wasapi_stream.close()
            except Exception:
                pass
            self._wasapi_stream = None
        if self._wasapi_wave is not None:
            try:
                self._wasapi_wave.close()
            except Exception:
                pass
            self._wasapi_wave = None
        if self._wasapi_manager is not None:
            try:
                self._wasapi_manager.terminate()
            except Exception:
                pass
            self._wasapi_manager = None

    def pause(self) -> None:
        """Toggle pause state."""
        self._is_paused = not self._is_paused
        # The WASAPI reader keeps draining the endpoint while paused, but drops
        # the samples so the resumed recording has no pause-time audio gap.
        if self._pw_process and self._pw_process.poll() is None:
            try:
                os.kill(self._pw_process.pid, signal.SIGSTOP if self._is_paused else signal.SIGCONT)
            except OSError:
                pass

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    def _resample(self, data: np.ndarray, orig_rate: int, target_rate: int) -> np.ndarray:
        """Resample audio data from orig_rate to target_rate using linear interpolation."""
        if orig_rate == target_rate:
            return data
        ratio = target_rate / orig_rate
        n_samples = int(len(data) * ratio)
        indices = np.linspace(0, len(data) - 1, n_samples)
        # Interpolate each channel
        if data.ndim == 1:
            return np.interp(indices, np.arange(len(data)), data).astype(data.dtype)
        resampled = np.zeros((n_samples, data.shape[1]), dtype=data.dtype)
        for ch in range(data.shape[1]):
            resampled[:, ch] = np.interp(indices, np.arange(len(data)), data[:, ch])
        return resampled

    def _normalize_frames(self, frames: list[np.ndarray], target_channels: int) -> np.ndarray:
        """Concatenate and normalize frames to the target channel count."""
        normalized: list[np.ndarray] = []
        for frame in frames:
            if frame.ndim == 1:
                # Mono → stereo
                frame = np.column_stack([frame, frame])
            if frame.shape[1] < target_channels:
                padding = np.zeros(
                    (frame.shape[0], target_channels - frame.shape[1]),
                    dtype=frame.dtype,
                )
                frame = np.hstack([frame, padding])
            elif frame.shape[1] > target_channels:
                frame = frame[:, :target_channels]
            normalized.append(frame)
        return np.concatenate(normalized, axis=0) if normalized else np.zeros((0, target_channels), dtype="float32")

    def stop(self) -> Optional[str]:
        """Stop recording and save to file. Returns the output path or None."""
        self._is_recording = False

        # Stop streams
        if self._system_stream is not None:
            try:
                self._system_stream.stop()
                self._system_stream.close()
            except Exception:
                pass
            self._system_stream = None

        if self._mic_stream is not None:
            try:
                self._mic_stream.stop()
                self._mic_stream.close()
            except Exception:
                pass
            self._mic_stream = None

        if self.record_system and os.name == "nt" and self._wasapi_manager is not None:
            self._stop_wasapi()
            if self._wasapi_error:
                console.print(f"[yellow]WASAPI loopback stopped: {self._wasapi_error}[/yellow]")
            audio_path = self._finish_external_system_audio(self._wasapi_wav_path)
            self._wasapi_error = None
            return audio_path

        if self._pw_process is not None:
            process = self._pw_process
            if process.poll() is None:
                try:
                    os.kill(process.pid, signal.SIGCONT)
                    process.send_signal(signal.SIGINT)
                    process.wait(timeout=15)
                except (OSError, subprocess.TimeoutExpired):
                    process.kill()
                    process.wait()
            self._pw_process = None
            return self._finish_pipewire_recording()

        # Build final audio data
        try:
            if not self._frames and not self._mic_frames:
                console.print("[yellow]No audio data was captured.[/yellow]")
                return None

            target_channels = CHANNELS

            # Process main frames (system audio, or mic-only)
            if self._frames:
                audio_data = self._normalize_frames(self._frames, target_channels)
                # Resample to output rate if this was mic-only and rates differ
                if not self.record_system and self.record_mic:
                    audio_data = self._resample(audio_data, self._mic_sample_rate, self._output_sample_rate)
            else:
                audio_data = np.zeros((0, target_channels), dtype="float32")

            # Mix in microphone if both were recorded
            if self.record_system and self.record_mic and self._mic_frames:
                mic_data = self._normalize_frames(self._mic_frames, target_channels)
                # Resample mic to match system sample rate if they differ
                mic_data = self._resample(mic_data, self._mic_sample_rate, self._system_sample_rate)

                # Mix by averaging (adjust lengths to shorter)
                min_len = min(len(audio_data), len(mic_data))
                if min_len > 0:
                    audio_data = audio_data[:min_len]
                    mic_data = mic_data[:min_len]
                    audio_data = (audio_data + mic_data) / 2.0

            if len(audio_data) == 0:
                console.print("[yellow]No audio data was captured.[/yellow]")
                return None

            # Save as WAV first, then convert to MP3 via FFmpeg
            wav_path = self.output_path.replace(".mp3", ".wav")
            sf.write(wav_path, audio_data, self._output_sample_rate)

            # Convert to MP3
            import subprocess

            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i", wav_path,
                    "-codec:a", "libmp3lame",
                    "-qscale:a", "2",
                    self.output_path,
                ],
                capture_output=True,
                text=True,
            )

            # Remove temporary WAV file
            try:
                Path(wav_path).unlink()
            except OSError:
                pass

            if result.returncode != 0:
                console.print(
                    f"[red]FFmpeg error converting to MP3: {result.stderr}[/red]"
                )
                return None

            return self.output_path

        except Exception as e:
            console.print(f"[red]Error saving audio: {e}[/red]")
            return None

    def _finish_pipewire_recording(self) -> Optional[str]:
        """Convert the PipeWire WAV capture, optionally mixing in microphone audio."""
        return self._finish_external_system_audio(self._pw_wav_path)

    def _finish_external_system_audio(self, wav_path: str) -> Optional[str]:
        """Convert an external system-audio WAV and optionally mix microphone input."""
        system_wav = Path(wav_path)
        if not system_wav.exists() or system_wav.stat().st_size == 0:
            console.print("[yellow]No system audio data was captured.[/yellow]")
            return None
        mic_wav = Path(self.output_path).with_suffix(".mic.wav")
        inputs = [str(system_wav)]
        if self.record_mic:
            mic_data = self._normalize_frames(self._mic_frames, CHANNELS)
            if len(mic_data):
                sf.write(str(mic_wav), mic_data, self._mic_sample_rate)
                inputs.append(str(mic_wav))
        cmd = ["ffmpeg", "-y"]
        for source in inputs:
            cmd += ["-i", source]
        if len(inputs) == 2:
            cmd += ["-filter_complex", "[0:a][1:a]amix=inputs=2:duration=longest:normalize=0[a]",
                    "-map", "[a]"]
        cmd += ["-codec:a", "libmp3lame", "-qscale:a", "2", self.output_path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                console.print(f"[red]FFmpeg error converting audio: {result.stderr[-500:]}[/red]")
                return None
            return self.output_path
        except (OSError, subprocess.SubprocessError) as e:
            console.print(f"[red]Could not finalize audio: {e}[/red]")
            return None
        finally:
            for temp in (system_wav, mic_wav):
                try:
                    temp.unlink()
                except OSError:
                    pass

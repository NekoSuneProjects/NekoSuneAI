"""Selected Windows microphone/loopback capture and TTS output, without local STT."""
from __future__ import annotations

import io
import threading
import wave


class NodeAudio:
    def __init__(self):
        self.stop_event = threading.Event()
        self.busy = threading.Lock()
        self.playing = threading.Event()
        # Set by capture() when the hard max_seconds cap was hit while the
        # speaker still sounded like they were mid-sentence (i.e. we gave up
        # before ever seeing silence_seconds of quiet), so the caller can
        # nudge them to keep it shorter next time instead of silently
        # truncating them.
        self.last_capture_truncated = False

    @staticmethod
    def devices():
        import pyaudiowpatch as pa
        with pa.PyAudio() as audio:
            inputs, outputs = [], []
            for index in range(audio.get_device_count()):
                device = audio.get_device_info_by_index(index)
                row = {"index": index, "name": device["name"], "loopback": bool(device.get("isLoopbackDevice"))}
                if device["maxInputChannels"]:
                    inputs.append(row)
                if device["maxOutputChannels"] and not row["loopback"]:
                    outputs.append(row)
            return {"inputs": inputs, "outputs": outputs}

    # RMS (on a [-1, 1] normalized mono mix) above this is treated as speech,
    # at/below it as silence. Plain amplitude threshold, not true VAD — good
    # enough to end-point "did they stop talking", not meant to reject noise.
    _SILENCE_RMS = 0.015

    def capture(self, device_index, max_seconds=30, silence_seconds=10, lead_silence_seconds=3):
        """Record until *silence_seconds* of continuous quiet follows some
        speech (i.e. they stopped talking), bailing early after
        *lead_silence_seconds* if nothing was ever said, and never recording
        past *max_seconds* regardless."""
        import numpy as np
        import pyaudiowpatch as pa
        import soxr
        max_seconds = float(max_seconds)
        silence_seconds = float(silence_seconds)
        lead_silence_seconds = float(lead_silence_seconds)
        if not 0 < max_seconds <= 120:
            raise ValueError("Max recording duration must be 0-120 seconds")
        if not 0 < silence_seconds <= 60:
            raise ValueError("Silence-to-finish must be 0-60 seconds")
        if not self.busy.acquire(blocking=False):
            raise RuntimeError("Audio is busy")
        try:
            self.stop_event.clear()
            self.last_capture_truncated = False
            with pa.PyAudio() as audio:
                info = audio.get_device_info_by_index(int(device_index))
                channels = min(2, int(info["maxInputChannels"]))
                if channels < 1:
                    raise ValueError("Select a microphone or loopback input")
                rate = int(info["defaultSampleRate"])
                frames_per_chunk = 1024
                chunk_seconds = frames_per_chunk / rate
                chunks = []
                elapsed = 0.0
                silence_elapsed = 0.0
                speech_started = False
                with audio.open(format=pa.paInt16, channels=channels, rate=rate, input=True,
                                input_device_index=int(device_index), frames_per_buffer=frames_per_chunk) as stream:
                    while elapsed < max_seconds and not self.stop_event.is_set():
                        data = stream.read(frames_per_chunk, exception_on_overflow=False)
                        chunks.append(data)
                        elapsed += chunk_seconds
                        chunk = np.frombuffer(data, dtype=np.int16).reshape(-1, channels).astype(np.float32).mean(axis=1) / 32768
                        rms = float(np.sqrt(np.mean(np.square(chunk)))) if chunk.size else 0.0
                        if rms > self._SILENCE_RMS:
                            speech_started, silence_elapsed = True, 0.0
                        else:
                            silence_elapsed += chunk_seconds
                        if speech_started and silence_elapsed >= silence_seconds:
                            break
                        if not speech_started and silence_elapsed >= lead_silence_seconds:
                            break
            if self.stop_event.is_set():
                raise RuntimeError("Recording cancelled")
            self.last_capture_truncated = speech_started and elapsed >= max_seconds and silence_elapsed < silence_seconds
            samples = np.frombuffer(b"".join(chunks), dtype=np.int16).reshape(-1, channels).astype(np.float32).mean(axis=1) / 32768
            samples = soxr.resample(samples, rate, 16000)
            pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
            result = io.BytesIO()
            with wave.open(result, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(pcm)
            return result.getvalue()
        finally:
            self.busy.release()

    def play(self, raw, device_index=None, cancelled=lambda: False):
        import numpy as np
        import pyaudiowpatch as pa
        import soundfile as sf
        import soxr
        if not self.busy.acquire(blocking=False):
            raise RuntimeError("Audio is busy recording or playing")
        try:
            if cancelled():
                raise RuntimeError("Speech cancelled")
            self.stop_event.clear()
            self.playing.set()
            with sf.SoundFile(io.BytesIO(raw)) as file:
                if file.frames > file.samplerate * 180:
                    raise ValueError("TTS audio exceeds three minutes")
                samples = file.read(dtype="float32", always_2d=True)
                source_rate = file.samplerate
            with pa.PyAudio() as audio:
                info = audio.get_default_output_device_info() if device_index is None else audio.get_device_info_by_index(int(device_index))
                channels = min(2, int(info["maxOutputChannels"]))
                if channels < 1:
                    raise ValueError("Select an output device")
                rate = int(info["defaultSampleRate"])
                samples = samples.mean(axis=1)
                samples = soxr.resample(samples, source_rate, rate)
                samples = np.repeat(samples[:, None], channels, axis=1).astype(np.float32)
                with audio.open(format=pa.paFloat32, channels=channels, rate=rate, output=True,
                                output_device_index=int(info["index"])) as stream:
                    for offset in range(0, len(samples), 1024):
                        if self.stop_event.is_set() or cancelled():
                            break
                        stream.write(samples[offset:offset + 1024].tobytes())
        finally:
            self.playing.clear()
            self.busy.release()

    def stop(self):
        self.stop_event.set()

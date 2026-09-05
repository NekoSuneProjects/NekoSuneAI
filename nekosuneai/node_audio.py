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

    def capture(self, device_index, seconds=5):
        import numpy as np
        import pyaudiowpatch as pa
        import soxr
        seconds = float(seconds)
        if not 0 < seconds <= 15:
            raise ValueError("Recording duration must be 0-15 seconds")
        if not self.busy.acquire(blocking=False):
            raise RuntimeError("Audio is busy")
        try:
            self.stop_event.clear()
            with pa.PyAudio() as audio:
                info = audio.get_device_info_by_index(int(device_index))
                channels = min(2, int(info["maxInputChannels"]))
                if channels < 1:
                    raise ValueError("Select a microphone or loopback input")
                rate = int(info["defaultSampleRate"])
                chunks = []
                remaining = int(seconds * rate)
                with audio.open(format=pa.paInt16, channels=channels, rate=rate, input=True,
                                input_device_index=int(device_index), frames_per_buffer=1024) as stream:
                    while remaining and not self.stop_event.is_set():
                        count = min(remaining, 1024)
                        chunks.append(stream.read(count, exception_on_overflow=False))
                        remaining -= count
            if self.stop_event.is_set():
                raise RuntimeError("Recording cancelled")
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

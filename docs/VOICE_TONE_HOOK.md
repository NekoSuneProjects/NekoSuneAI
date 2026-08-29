# Pi microphone tone capture hook

The existing `audio_input.recognize_speech()` function already receives the complete `SpeechRecognition.AudioData` utterance before transcription. The lightweight tone analyzer in `nekosuneai.voice_tone` is designed to consume `audio.get_wav_data()` at that point, so tone analysis can reuse the exact STT utterance without opening a second microphone stream.

Recommended capture-point integration:

```python
from .voice_tone import analyze_voice_wav

try:
    analyze_voice_wav(audio.get_wav_data())
except Exception:
    pass
```

`analyze_voice_wav()` stores the latest cue in normal app state. `webserver.py` reads that cue for up to 30 seconds and includes it as tentative companion context.

The hook must remain failure-safe: STT should continue normally even if acoustic analysis fails.

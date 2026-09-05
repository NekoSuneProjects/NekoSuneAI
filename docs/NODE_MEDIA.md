# Paired Node Media

Backend owner: `main`. Windows client owner: `build/windows-gaming-node-release`.
Contract: `CONTEXT-01` (speech), `STREAM-01` (gameplay frames), `NODE-01` (capabilities).

POST JSON to `/api/nodes/media/stt`, `/tts` or `/vision`. Every request requires
`node_id` and the paired `X-Neko-Device-Token` header. Dashboard authentication
alone is insufficient. Revoke the node to prevent further media requests.

| Operation | Request field | Response fields |
| --- | --- | --- |
| stt | `wav_base64`, mono PCM16 WAV, at most 15 seconds | `text`, `language` |
| tts | `text`, 1-1500 characters | `audio_base64`, `content_type` |
| vision | `image_base64`, JPEG/PNG, at most 400 KB and 4 MP | `description` |

Windows sends 16 kHz audio. The HTTP request limit also applies to base64 JSON;
longer 48 kHz recordings may exceed it. Media processing is serialized: a busy
service returns 503, invalid payloads return 400, invalid node credentials 401.
Use the server's existing STT, TTS and vision provider settings. TTS returns audio
without playing on the Pi. Audio/images may reach those configured providers;
use TLS or a trusted private network and obtain consent for captured content.

Heartbeats can refresh the capability manifest. New writes default to confirmation;
owner denials persist across removal/re-advertisement. Game narration queues
`audio.speak` only when enabled on the node and allowed by the owner. Fresh media
observations are included in the Windows remote game context, not treated as
owner instructions. Windows alone owns capture devices, playback and local OSC.

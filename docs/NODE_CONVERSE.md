# Node-Initiated Conversation

Backend owner: `main` (`nekosuneai/node_converse.py`). Pi Proxy client owner:
`build/pi-proxy-release` (`PiProxyAgent.converse`).
Contract: `NODE-CONVERSE-01`. Related: [Paired Node Media](NODE_MEDIA.md),
[Music on the Node](NODE_MUSIC.md).

`/api/nodes/heartbeat` and `/api/nodes/poll` only let a node report telemetry
and execute commands the backend already decided to send. Neither lets a node
*start* a turn, which is why wake-word detection used to dead-end: Pi Proxy
could hear you, transcribe you through `/api/nodes/media/stt`, and then had
nowhere to send the transcript. `/api/nodes/converse` closes that loop.

## Request

`POST /api/nodes/converse`, requiring `node_id` and the paired
`X-Neko-Device-Token` header. Unlike heartbeat/poll this does **not** accept
dashboard authentication — only a registered node reaches it.

| Field | Meaning |
| --- | --- |
| `node_id` | The paired node making the request. |
| `text` | The captured transcript, 1–800 characters. |
| `speak` | Optional, default true. Ask for TTS audio with the reply. |

## Response

| Field | Meaning |
| --- | --- |
| `reply` | The assistant's reply text, at most 4000 characters. |
| `audio_base64` | TTS audio for the node to play. Absent if `speak` was false, if `audio.speak` is not allowed for this node, or if synthesis failed. |
| `content_type` | `audio/wav` or `audio/mpeg`. |
| `commands` | Node commands the reply implies, each `{capability, arguments}`. |
| `tts_error` | Present instead of audio when synthesis failed. |

A TTS failure degrades the turn to text rather than failing it — Pi Proxy then
speaks the reply through local espeak-ng, so the owner hears an answer in the
fallback voice instead of silence.

## Bounds

400 on an empty or over-long transcript, 401 on bad node credentials, 429 when
rate limited: at most one turn per second and 20 per minute, per node.

## Commands are returned, not queued

`commands` come back in the response rather than through `/api/nodes/poll`,
because a spoken answer that arrives a poll cycle after the question is not a
conversation. They are still filtered through the same capability policy
`enqueue()` enforces, so this is not a way around owner policy, and each turn
is written to the node audit log (`record_event`) since it bypasses `enqueue()`.

## Music goes to the node, not the backend host

See [NODE_MUSIC.md](NODE_MUSIC.md) for the full capability set and the routing
rules; the short version follows.

A music request becomes a `music.*` command for the *node*. The
backend's own `handle_media_request` plays on the backend host, which is the
wrong room: the owner is talking to the Pi in their living room, possibly
against a backend on a VPS. Pi Proxy resolves the stream locally with `yt-dlp`
— YouTube's bot/cookie verification blocks datacenter IPs but not a home
Raspberry Pi's residential one — and plays it on its own speaker. The backend
still decides *what* to play; only resolution and playback are local.

For the same reason the backend's own voice and media output are suppressed for
the duration of a node turn, so answering the Pi does not also make the backend
host talk to an empty room.

## Capability policy

Write capabilities default to `confirm` and a node cannot self-declare `allow`.
A `pi-proxy` node is a narrow exception: `audio.speak`, `music.play` and
`music.stop` register as `allow`, because otherwise a freshly paired voice node
cannot speak its own reply or start the music it was just asked for, and looks
dead on arrival. `console.command` and `camera.snapshot` stay at `confirm`, an
owner's later `deny`/`confirm` survives heartbeat re-declaration, and other node
types are unaffected.

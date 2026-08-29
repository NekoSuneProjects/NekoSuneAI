# Raspberry Pi Smart Speaker, YouTube Music, Reminders and Scheduled Monitors

This feature is designed for a home-hosted NekoSuneAI Raspberry Pi. It does not need a VPS or a YouTube API key.

## YouTube music

NekoSuneAI uses `yt-dlp` to search YouTube and resolve an audio-only stream URL, then streams it directly through `ffplay`. Songs are not permanently downloaded.

Examples:

```text
Neko, play Alan Walker Faded
Neko, pause the music
Neko, resume the music
Neko, next song
Neko, previous song
Neko, stop the music
Neko, music volume 60
Neko, turn the music up
Neko, turn the music down
Neko, what's playing?
```

Search ranking prefers official video/audio, VEVO and artist Topic results and penalises covers, karaoke, reaction and slowed/sped-up versions. `YOUTUBE_MUSIC_VOLUME=75` sets startup music volume separately from TTS volume.

## Saved playlists

Playlists use NekoSuneAI's existing persistent database state and survive restarts when `/app/data` is persistent. Each track stores a stable YouTube page URL and resolves a fresh audio URL before playback.

## Reminders, timers and alarms

```text
Neko, remind me in 20 minutes to check the oven
Neko, remind me at 7 PM to feed the dog
Neko, set a timer for 10 minutes
Neko, set an alarm for 7 AM
Neko, wake me at 7 AM
```

These persist in SQLite across Pi/container restarts.

## Timed monitor schedules

```text
Neko, monitor aircraft 1 PM to 4 PM every Friday
Neko, track military aircraft from 13:00 to 16:00 every Friday
Neko, monitor weather from 8 AM to 10 PM every day
```

Outside the selected window no monitor MCP/API calls are made. The fallback timezone is `Europe/London`.

## Shared VRM avatar

```env
VRM_AVATAR_URL=https://your-host/avatar.vrm
```

The Pi dashboard central stage loads this VRM while small loading/sidebar logos stay static. The renderer supports blinking, idle breathing/head movement, happy/sad/angry/excited/relaxed/scared expressions, hand/arm gestures, guarded/slouched poses, and VRM vowel visemes (`aa`, `ih`, `ou`, `ee`, `oh`).

TTS animation uses the exact text being spoken to generate a synchronized viseme sequence. The event protocol is intentionally separate from the renderer, so a TTS engine that later provides real phoneme/viseme timestamps can replace the estimator without changing the VRM UI.

## Persistent simulated mood

`nekosuneai/mood_state.py` stores a bounded affect model with valence, arousal, trust and caution. Repeated supportive or hostile interaction can shift the avatar's expression, posture and TTS emotion selection, then the state gradually decays back toward a calm mildly-positive baseline.

This is a software personality simulation, not a claim that NekoSuneAI is sentient or has biological emotional needs. The mood prompt/rules explicitly prohibit guilt, threats, dependency language, or telling the user they must stay/provide attention.

## Phone camera vision

The Android companion has an explicit foreground camera mode. While its preview screen is open it uses CameraX at 640x480 and sends at most one compressed frame about every five seconds to:

```text
POST /api/android/vision
```

The Pi runs the existing NekoSuneAI vision backend, keeps only a short factual description for roughly 20 seconds of conversational context, and does not persist the raw image. Leaving the Android camera screen stops sharing.

## Kinect / external camera vision

Both Kinect generations can feed the same endpoint without bloating the base Docker image with generation-specific drivers. Kinect v1/360 can use `libfreenect`; Kinect v2 can use `libfreenect2`. Have the local capture process refresh a JPEG/PNG file and run:

```bash
python tools/kinect_vision_bridge.py \
  --server https://your-neko-host \
  --token "$WEB_DASHBOARD_TOKEN" \
  --frame /tmp/kinect.jpg \
  --interval 5
```

The bridge only sends a newly refreshed frame and can be stopped with Ctrl+C.

## Vision privacy

Camera access is opt-in. The vision prompt is restricted to visible, non-sensitive facts such as objects, posture, obvious gestures and actions. It is instructed not to identify people or infer sensitive traits. Do not expose the raw dashboard port to the public internet; use Tailscale/VPN or authenticated HTTPS.

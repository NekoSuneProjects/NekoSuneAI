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

Search ranking prefers official video/audio, VEVO and artist Topic results and penalises covers, karaoke, reaction and slowed/sped-up versions.

`YOUTUBE_MUSIC_VOLUME=75` sets the startup music volume. Music volume is separate from NekoSuneAI TTS voice output.

YouTube can change its site or challenge a residential IP. Keep `yt-dlp` current. If your own signed-in YouTube session is required, mount a private cookies file and set `YTDLP_COOKIES_FILE`. Never commit cookies.

## Saved playlists

Playlists use NekoSuneAI's existing persistent database state and survive restarts when `/app/data` is persistent.

```text
Neko, create a playlist called Frenchcore
Neko, add Dr Peacock Trip to Valhalla to my Frenchcore playlist
Neko, import playlist https://www.youtube.com/playlist?list=YOUR_LIST_ID as Frenchcore
Neko, play my Frenchcore playlist
Neko, list my playlists
```

Each track is stored as a stable YouTube page URL. A fresh audio CDN URL is resolved immediately before each song starts. When one song ends the next begins automatically.

## Reminders, timers and alarms

These are stored locally in NekoSuneAI's database and continue working after Pi/container restarts.

```text
Neko, remind me in 20 minutes to check the oven
Neko, remind me at 7 PM to feed the dog
Neko, set a timer for 10 minutes
Neko, set an alarm for 7 AM
Neko, wake me at 7 AM
Neko, list reminders
Neko, cancel reminder 12ab34cd
```

When due, reminders/timers/alarms use the same NekoSuneAI notification path as monitor alerts, allowing Pi voice and connected mobile notification handling.

## Timed 24/7 monitor schedules

NekoSuneAI itself can run 24/7 while expensive/API-backed monitors only run inside selected windows.

```text
Neko, monitor aircraft 1 PM to 4 PM every Friday
Neko, track military aircraft from 13:00 to 16:00 every Friday
Neko, monitor weather from 8 AM to 10 PM every day
Neko, monitor aircraft from 1 PM to 4 PM on Saturday and Sunday
Neko, list timed monitor schedules
```

The default polling interval is five minutes inside the allowed window unless another interval is spoken. Outside the window there are no monitor MCP/API calls. The schedule automatically resumes on the next selected day and survives restarts.

The fallback timezone is `Europe/London`.

## Shared VRM avatar

Set one avatar URL on the Pi:

```env
VRM_AVATAR_URL=https://your-private-or-public-host/avatar.vrm
```

The Pi dashboard's large central avatar stage is upgraded from the static logo to a live VRM renderer at serve-time. Loading/sidebar logos remain lightweight images.

The VRM supports lightweight idle movement, blinking, mouth motion while speaking, and basic emotion expressions such as neutral, happy, sad, angry and excited when the model exposes compatible VRM expressions.

`GET /api/avatar/config` is token protected. The Android companion uses this endpoint so the phone and Pi load the same configured avatar.

## Self-hosted smart-speaker scope

Together with NekoSuneAI's existing features, the Pi can cover much of a local Alexa/Google-Home-style workflow without sending every command to a proprietary home speaker:

- wake-word/voice chat
- YouTube music and playlists
- transport and music volume controls
- reminders, alarms and timers
- weather/rain/warnings
- aircraft and other MCP monitors
- selected-day/time schedules
- Home Assistant integration for smart-home devices
- web and Android remote chat
- VRM companion UI

Future routines can build on the same local database/scheduler rather than requiring a cloud assistant account.

## Residential IP / remote Android access

A residential IP is fine because music and monitors primarily make outbound HTTPS requests. No inbound public port is needed for local playback.

For Android access away from home, do **not** expose the raw NekoSuneAI dashboard port through ordinary router port-forwarding. Prefer Tailscale, another VPN, or an authenticated HTTPS tunnel/reverse proxy. Keep `WEB_DASHBOARD_TOKEN` enabled as an additional application-level secret.

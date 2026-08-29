# Raspberry Pi YouTube Music + Scheduled Monitors

This feature is designed for a home-hosted NekoSuneAI Raspberry Pi. It does not need a VPS or a YouTube API key.

## YouTube music

NekoSuneAI uses `yt-dlp` to search YouTube and resolve an audio-only stream URL, then sends that URL directly to `ffplay`. Audio is streamed and is not downloaded into a permanent music library.

Example requests:

```text
Neko, play Alan Walker Faded
Neko, stop the music
Neko, next song
Neko, what's playing?
```

Search results are scored to prefer titles containing `Official Video` / `Official Audio`, VEVO channels, and artist Topic channels, while reducing the score of covers, slowed/sped-up versions, reactions and karaoke results.

YouTube can still change its site or occasionally challenge residential IP addresses. Keep `yt-dlp` current. If your own YouTube session is required, set `YTDLP_COOKIES_FILE` to a cookies file mounted privately into the container. Never commit cookies to Git.

The Docker image already installs FFmpeg, including `ffplay`.

Optional volume:

```env
YOUTUBE_MUSIC_VOLUME=75
```

## Saved playlists

Playlists are stored in NekoSuneAI's existing persistent database state. They therefore survive application/container restarts as long as the normal `/app/data` volume is persisted.

Examples:

```text
Neko, create a playlist called Frenchcore
Neko, add Dr Peacock Trip to Valhalla to my Frenchcore playlist
Neko, add Sefa 1527 to my Frenchcore playlist
Neko, play my Frenchcore playlist
Neko, list my playlists
```

Songs are played sequentially. When one `ffplay` process exits naturally, NekoSuneAI resolves a fresh audio stream for the next video and starts it automatically.

### Import an existing YouTube playlist

```text
Neko, import playlist https://www.youtube.com/playlist?list=YOUR_LIST_ID as Frenchcore
```

The import stores the stable YouTube video URLs and titles. It does not store temporary Google CDN media URLs.

## Timed 24/7 monitor schedules

NekoSuneAI itself can remain running 24/7 while individual monitors are active only inside selected time windows.

Examples:

```text
Neko, monitor aircraft from 1 PM to 4 PM every Friday
Neko, monitor aircraft 1 PM to 4 PM every Friday
Neko, track military aircraft from 13:00 to 16:00 every Friday
Neko, monitor weather from 8 AM to 10 PM every day
Neko, monitor aircraft from 1 PM to 4 PM on Saturday and Sunday
```

If no polling interval is spoken, the monitor checks every 5 minutes while inside the window. You can also say:

```text
Neko, monitor aircraft from 1 PM to 4 PM every Friday every 2 minutes
```

Outside the configured window, the monitor makes no MCP/API calls. When the next allowed day/time arrives it resumes automatically. Schedules are persisted in the existing NekoSuneAI database, so a Pi reboot or container restart does not erase them.

The default timezone is `Europe/London` unless NekoSuneAI's Config exposes another timezone.

Management examples:

```text
Neko, list timed monitor schedules
Neko, stop timed monitor 12ab34cd
```

## Residential IP notes

A home residential IP is fine for this architecture. The Pi makes outbound HTTPS requests to YouTube and to whatever MCP/public data providers your monitors use. No inbound public port is required for music playback.

For the web/mobile dashboard, keep using a private VPN such as Tailscale or a properly authenticated HTTPS tunnel/reverse proxy rather than exposing the raw dashboard port directly.

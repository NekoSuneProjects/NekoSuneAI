# Music on the Node, Not the Backend

Backend owner: `main` (`nekosuneai/node_music.py`). Pi Proxy client owner:
`build/pi-proxy-release` (`nekosuneai/music.py`).
Related: [Node-Initiated Conversation](NODE_CONVERSE.md).

## Why

The backend's own `YouTubeMusicPlayer` resolves streams with yt-dlp and plays
them with ffplay **on whatever machine runs the backend**. For a backend on a
VPS that is wrong twice over:

1. **YouTube blocks datacenter IPs.** A VPS gets "confirm you're not a robot"
   and "sign in to confirm your age" where a home Raspberry Pi's residential
   IP resolves the same video without complaint.
2. **The speaker is in the wrong building.** The owner asking for music is at
   home next to the Pi, not in the datacenter.

So when a Pi Proxy node is online and advertises `music.play`, music requests
become node commands. The backend still decides *what* to play — this is a
routing layer over the phrasing `handle_music_request` already understood, not
a second music brain. With no such node online the backend falls through to
its own player, so a deployment without a Pi Proxy is unchanged.

## Capabilities

| Capability | Kind | Arguments |
| --- | --- | --- |
| `music.play` | write | `query` or `url`, or `queries` for a whole playlist; `queue: true` appends instead of replacing |
| `music.stop` | write | — |
| `music.pause` | write | — |
| `music.resume` | write | — |
| `music.skip` | write | `previous: true` goes back a track |
| `music.volume` | write | `percent`, 0–100 |
| `music.status` | read | — |

All except `music.status` are writes. They are in the `pi-proxy` auto-allow
list (see [NODE_CONVERSE.md](NODE_CONVERSE.md#capability-policy)), so a freshly
paired node can be asked for music without the owner flipping seven switches
first. An owner's later `deny`/`confirm` still wins.

## Choosing the node

Automatic: the online `pi-proxy` node advertising `music.play`. With several
online the lowest `node_id` wins, deterministically rather than whichever the
registry happened to list first. Set `MUSIC_NODE_ID` on the backend to pin one.

A node turn is different: when the owner speaks *to a node*, its own commands
go back to that node, so talking to the kitchen Pi never starts music in the
living room.

## Where the queue lives

On the node. The gap between tracks would otherwise be a full network round
trip — node reports idle, backend notices, backend sends the next track —
which is audible. The backend can hand over a whole playlist in one
`music.play` and the node advances locally. A track that fails to resolve is
skipped with a note rather than stranding the rest of the queue.

`music.status` is answered from the node's heartbeat state rather than by
queuing a command and waiting for the reply, so "what's playing" is instant.

## How playback works

No new dependency: everything below is already in the Pi Proxy image.

| Step | Tool |
| --- | --- |
| Resolve a query/URL to a stream | `yt-dlp` |
| Play it, no video | `ffplay` (ffmpeg) |
| Pause / resume | `SIGSTOP` / `SIGCONT` on that process |
| Volume | `pactl set-sink-volume @DEFAULT_SINK@` |

Pausing by stopping the reader is the honest thing for a live network stream.
`SIGSTOP`/`SIGCONT` are POSIX-only; on a host without them pause reports itself
as unsupported rather than silently doing nothing. Stopping a paused track
sends `SIGCONT` first — a stopped process will not act on `SIGTERM` until it
runs again.

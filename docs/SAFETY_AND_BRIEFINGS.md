# Safety, Home Timeline and Briefings

This batch adds local, deterministic safety handling and source-attributed
briefings. These features do not replace certified smoke, carbon-monoxide,
security or leak alarms, emergency services, or professional safety advice.

## Local emergency sensor broadcasts

Home Assistant or generic MQTT `binary_sensor` entities with a supported
`device_class` are evaluated locally:

- `smoke`
- `carbon_monoxide`
- `gas`
- `moisture`
- `safety`

An inactive-to-active transition produces a `danger` notification for the web
dashboard, configured mobile notifier and normal local announcement path. A
repeated identical active state does not create another broadcast. A later
clear transition produces a warning that the physical area still needs to be
verified. Sensor names containing unambiguous smoke, leak/flood or security
terms are supported as a fallback when a device omits its class.

Sensitive commands remain fail-closed. Smart-home `unlock`, `open`, and
`disarm` requests require `confirmed: true`; peripheral-node write capabilities
use their own allow/confirm/deny policy. Routines resolve those policies again
before execution.

## Local home timeline

State changes, occupancy transitions, node heartbeats and safety incidents are
stored in `data/home_timeline.json`. Configure:

```env
HOME_TIMELINE_FILE=data/home_timeline.json
HOME_TIMELINE_RETENTION_DAYS=30
```

Retention is bounded to 2,000 events and the configured number of days.
Credential-like fields (`token`, `password`, `secret`, `authorization`, and
similar keys) are removed before persistence. The authenticated endpoint is:

```text
GET /api/home/timeline?hours=24&category=safety&room=kitchen&limit=100
```

Natural queries include `what happened at home in the last 8 hours?`,
`home timeline`, and `when did the front door last open?`.

## House and RSS briefings

`give me a house status briefing` reports discovered-device/node availability,
local sensor temperatures, low batteries, offline devices and active emergency
incidents. It uses local persisted state and remains available when the Internet
is down.

`local weather station readings` summarises temperature, humidity, pressure,
rain and wind fields reported by local MQTT/Home Assistant sensors. Existing
MCP weather monitors continue to provide forecast, rain ETA, storm/warning and
lightning-risk alerts; those remote results identify themselves as scheduled
weather updates and do not overwrite local station readings.

RSS is opt-in. Configure a comma-separated list of sources:

```env
RSS_BRIEFING_FEEDS=https://example.org/news.rss,https://example.net/updates.atom
```

Ask for `news briefing` or `RSS briefing`. Neko fetches at most 2 MB per feed
with a short timeout, returns a maximum of ten headlines, identifies each feed,
includes article links when supplied, and explicitly warns that headlines may
be incomplete, developing or disputed. Configure sources you trust; a feed's
presence does not make its claims true. Feed failures are reported instead of
being silently invented or filled by the language model.

MQTT, Home Assistant, Android companions, peripheral PC/Pi/custom nodes and
manual routines remain optional peers. None is required for another to exist,
although a specific briefing naturally reports only integrations that are
configured and currently providing data.

# Local Smart Home with Home Assistant API and MQTT

NekoSuneAI can connect directly to a self-hosted Home Assistant instance and
use Home Assistant as an integration hub. This works with Home Assistant OS,
Container, Supervised and other installs that expose the standard API. Existing
Xbox, TV, Chromecast, DLNA, vacuum, climate, light, cover, scene, script and
other supported Home Assistant entities can therefore be controlled without
writing a separate NekoSuneAI driver for each brand.

MQTT remains optional and can run alongside the direct API. NekoSuneAI can
discover and control local MQTT devices without requiring a cloud account. It
understands standard Home Assistant MQTT discovery records
and a small vendor-neutral Neko discovery format. All commands are restricted
to topics declared by a discovered device; there is no arbitrary MQTT publish
method exposed to chat.

## Direct Home Assistant API

Create a **Long-Lived Access Token** from the Home Assistant user profile, then
configure NekoSuneAI in **Settings → Wake Word & Home Assistant**, or use:

```env
HOME_ASSISTANT_URL=http://homeassistant.local:8123
HOME_ASSISTANT_TOKEN=replace-with-long-lived-token
HOME_ASSISTANT_VERIFY_TLS=true
HOME_ASSISTANT_WEBSOCKET_ENABLED=true
```

The REST API is used for entity discovery and entity-scoped service calls.
The WebSocket API subscribes to `state_changed` so Xbox/TV/media and other
entity state stays current without repeatedly polling. The token is never
returned by NekoSuneAI status endpoints.

Natural examples include:

```text
turn on living room xbox
what is living room xbox playing?
pause on living room xbox
launch Netflix on living room tv
switch living room tv source to HDMI 2
set living room tv volume to 35%
press home on living room remote
set bedroom blinds position to 40%
set heating to 21 degrees
start robot vacuum
activate movie mode
```

NekoSuneAI only exposes an explicit allowlist of entity services. Arbitrary
Home Assistant service calls/templates are not exposed to chat, and sensitive
actions such as unlocking a lock still require confirmation.

## Optional MQTT configuration

```env
HA_MQTT_HOST=192.168.1.20
HA_MQTT_PORT=1883
HA_MQTT_USERNAME=nekosuneai
HA_MQTT_PASSWORD=replace-me

# Room containing this Neko microphone/node. This lets "turn the light off"
# resolve only against lights in the room where the request was heard.
NEKOSUNEAI_ROOM=kitchen

# Used for the cost shown beside cumulative energy_kwh telemetry.
ELECTRICITY_PRICE_PER_KWH=0.25
SMART_HOME_DEVICES_FILE=data/smart_home_devices.json
```

Use a dedicated least-privilege broker account and keep the broker on a trusted
LAN or VPN. Do not expose an unauthenticated MQTT broker to the Internet.

## Home Assistant discovery

Neko subscribes to retained `homeassistant/#` discovery records. Supported
components are `light`, `switch`, `fan`, `cover`, `lock`, `climate`, `sensor`
and `binary_sensor`. It reads the common full and abbreviated fields including:

- `unique_id`, `name`, `device`, `room`/`area`, and `~`
- `device_class` / `dev_cla` for local motion, presence and occupancy sensors
- `state_topic` / `stat_t`
- `command_topic` / `cmd_t`
- `availability_topic` / `avty_t`
- `json_attributes_topic` / `json_attr_t`
- `brightness_command_topic` / `bri_cmd_t`
- `payload_on`, `payload_off`, and `brightness_scale`

When a discovery record arrives, Neko subscribes to its declared state,
attributes and availability topics. MQTT's reconnect backoff is enabled and
all persisted state topics are resubscribed after reconnection.

## Generic Neko discovery

Publish a retained JSON record to:

```text
nekosuneai/devices/DEVICE_ID/config
```

Example:

```json
{
  "unique_id": "desk-plug",
  "name": "Desk Plug",
  "component": "switch",
  "room": "office",
  "aliases": ["computer plug", "my plug"],
  "command_topic": "house/office/desk-plug/set",
  "state_topic": "house/office/desk-plug/state",
  "availability_topic": "house/office/desk-plug/availability",
  "payload_on": "ON",
  "payload_off": "OFF"
}
```

State can be a simple value or a JSON object. Recognised telemetry keys include
`battery`, `battery_percent`, `power`, `power_w`, `watts`, `energy`, and
`energy_kwh`.

## Commands, rooms and aliases

Open **Studio → Nodes & Routines → Smart-home devices** to see availability,
state, room, aliases, battery and estimated energy cost. You can change aliases
and room assignments there.

Examples:

```text
turn the light off
turn my lamp on
set main light brightness to 20
what is desk plug energy?
what is controller battery?
is anyone in the hallway?
is anyone home?
```

Generic names such as `the light` are resolved inside `NEKOSUNEAI_ROOM`.
Ambiguous matches stop with an explanation instead of choosing a random device.
Sensors and binary sensors are read-only. Sensitive actions such as unlock/open
require explicit confirmation when invoked through the authenticated API.

## Battery and energy intelligence

Battery readings are retained as a small local rolling history. When enough
time-separated samples exist, Neko estimates the recent discharge rate and
time to 5%. A battery at or below 15% creates a cooldown-protected warning.

Power readings keep a bounded rolling baseline. A reading significantly above
both the recent mean and deviation raises one cooldown-protected unusual-usage
warning. Cumulative kWh is multiplied by `ELECTRICITY_PRICE_PER_KWH` for a
simple estimated cost; this is informational and does not replace a utility
meter or tariff bill.

Every device state update emits these local routine events:

```text
smart_home.DEVICE_ID.state
smart_home.state
```

The routine condition context contains `device` and, for the device-specific
event, `smart_home.DEVICE_ID`. This allows sensor-driven routines while keeping
the routine action permission checks from the peripheral-node layer.

Binary sensors with a `motion`, `presence`, or `occupancy` device class also
maintain a per-room occupied/vacant summary and emit transition-only events:

```text
presence.changed
presence.ROOM.occupied
presence.ROOM.vacant
```

The generic event includes `presence.room`, `presence.occupied`, and the local
sensor ID. Presence-triggered routines and one-shot reminders consume this
event. For example, `remind me about washing when I next go downstairs` stays
local, fires on the next matching occupied transition, and then deactivates.

Safety-class binary sensors (`smoke`, `carbon_monoxide`, `gas`, `moisture`, or
`safety`) use the same local state path for transition-only emergency
broadcasts and clear notices. See
[`SAFETY_AND_BRIEFINGS.md`](SAFETY_AND_BRIEFINGS.md) for limitations and the
retained event timeline.

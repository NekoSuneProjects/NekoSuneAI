# Local Smart Home with Home Assistant and MQTT

NekoSuneAI can discover and control local MQTT devices without requiring a
cloud account. It understands standard Home Assistant MQTT discovery records
and a small vendor-neutral Neko discovery format. All commands are restricted
to topics declared by a discovered device; there is no arbitrary MQTT publish
method exposed to chat.

## Configuration

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

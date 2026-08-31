# Peripheral Nodes and Routines

NekoSuneAI now has a local-first HTTP protocol for lightweight phone, Pi,
desktop, sensor, display, printer and other owner-controlled nodes. Nodes only
receive capabilities that they declared while pairing; there is no generic
remote shell endpoint.

Open `/automations?token=<WEB_DASHBOARD_TOKEN>` (or use the **Nodes &
Routines** button in Studio) for the visual pairing, status and routine builder
page.

All dashboard requests use either `X-Neko-Token: <WEB_DASHBOARD_TOKEN>` or the
`?token=` query parameter. Node requests use the one-time plaintext token from
registration as `X-Neko-Device-Token`. Only its SHA-256 digest is stored.

## Pair a node

1. From the authenticated dashboard, request a short-lived code:

   ```http
   POST /api/nodes/pairing
   X-Neko-Token: DASHBOARD_TOKEN
   Content-Type: application/json

   {"name":"Kitchen Pi","ttl_seconds":300}
   ```

2. Register the node once with the returned ID and code:

   ```http
   POST /api/nodes/register
   Content-Type: application/json

   {
     "pairing_id":"RETURNED_ID",
     "pairing_code":"RETURNED_CODE",
     "node_id":"pi-kitchen",
     "name":"Kitchen Pi",
     "node_type":"raspberry-pi",
     "capabilities":{
       "sensor.temperature":{"kind":"read"},
       "audio.speak":{"kind":"write"},
       "display.notify":{"kind":"write"}
     }
   }
   ```

   Save `device_token` from this response. It is shown once. Read capabilities
   default to `allow`; write capabilities default to `confirm`.

3. Send telemetry and state:

   ```http
   POST /api/nodes/heartbeat
   X-Neko-Device-Token: DEVICE_TOKEN
   Content-Type: application/json

   {
     "node_id":"pi-kitchen",
     "latency_ms":12,
     "battery_percent":81,
     "state":{"temperature_c":22.4,"audio":"idle"},
     "ack_command_id":14
   }
   ```

4. Long-poll for commands (maximum 30 seconds per request):

   ```http
   POST /api/nodes/poll
   X-Neko-Device-Token: DEVICE_TOKEN
   Content-Type: application/json

   {"node_id":"pi-kitchen","after":0,"wait_seconds":25}
   ```

   After completing commands, send the highest completed ID as
   `ack_command_id` in the next heartbeat so acknowledged queue entries are
   removed.

The dashboard can inspect `GET /api/nodes`, inspect the local audit trail at
`GET /api/nodes/audit`, change a capability policy with
`POST /api/nodes/policy`, enqueue an allowlisted action with
`POST /api/nodes/command`, or revoke a node with `POST /api/nodes/revoke`.

## Routines

Routines contain one or more manual/event/sensor triggers, deterministic
conditions and ordered node-capability actions. They are stored locally in
`data/routines.json`. Set `ROUTINES_FILE` or `PERIPHERAL_NODES_FILE` only when
you need different persistent paths.

Create a routine with the authenticated API:

```http
POST /api/routines
X-Neko-Token: DASHBOARD_TOKEN
Content-Type: application/json

{
  "action":"create",
  "routine":{
    "name":"Movie mode",
    "triggers":[{"type":"event","event":"movie.requested"}],
    "conditions":[
      {"path":"room.occupied","operator":"eq","value":true}
    ],
    "actions":[
      {
        "node_id":"living-room",
        "capability":"light.set",
        "arguments":{"brightness":20},
        "undo":{
          "node_id":"living-room",
          "capability":"light.set",
          "arguments":{"brightness":100}
        }
      }
    ]
  }
}
```

Available endpoints:

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/routines` | List routines |
| `POST` | `/api/routines` | Create, update or delete |
| `POST` | `/api/routines/preview` | Evaluate conditions without executing |
| `POST` | `/api/routines/run` | Run by ID/name; pass `confirmed: true` when required |
| `POST` | `/api/routines/event` | Submit an event/sensor trigger and context |
| `POST` | `/api/routines/undo` | Undo the last completed routine when prior state is known |
| `GET` | `/api/routines/conflicts` | Find routines fighting over one target/event |
| `GET` | `/api/routines/explain?routine=...` | Explain the latest success or failure |

Five or more actions, or any action with `requires_confirmation: true`, pauses
for explicit confirmation. A node's own capability policy is checked again at
queue time, so a routine cannot bypass a denied or confirmation-required
device action. Add `expires_epoch` for a temporary routine.

Spoken/text commands currently include `run movie mode`,
`why did movie mode run?`, and `undo the last routine`.

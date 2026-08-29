# NekoSuneAI Android Companion

The native Android companion lives in `android/` and connects a phone to the Pi-hosted NekoSuneAI web service.

## Current feature set

- low-power persistent connection to the Raspberry Pi
- 25-second HTTP long-poll for commands instead of rapid polling
- telemetry heartbeat every 5 minutes
- battery percentage and charging state
- battery current, voltage and reported battery temperature
- Android thermal status
- available/total RAM and Android low-memory signal
- free/total internal storage
- device model and Android SDK version
- optional Android notification access
- forwards notification app, title/sender and text preview to NekoSuneAI
- message preview forwarding can be disabled in preferences
- Google Messages, Samsung Messages, WhatsApp, Discord and other apps can be surfaced through their normal Android notifications without making NekoSuneAI the default SMS app
- Find My Phone mode raises ringtone volume to maximum and loops the phone ringtone
- persistent Find My Phone notification includes a STOP action
- Pi commands can stop the ringing remotely
- natural NekoSuneAI requests supported by the Pi-hosted web instance:
  - `find my phone`
  - `where is my phone`
  - `stop ringing my phone`
  - `what is my phone battery?`
  - `is my phone charging?`
  - `what is my phone status?`
  - `show my latest phone notifications`
- built-in VRM avatar viewer using Three.js + `@pixiv/three-vrm`
- Android APK GitHub Actions workflow

## Performance / heat design

The companion is intentionally not an always-running profiler.

Commands use one blocking HTTP long-poll request. The request sleeps in the network stack until a command arrives or the 25-second server wait expires, so there is no tight CPU loop.

Telemetry is sampled once every five minutes. Android notification data is sent only when Android itself wakes `NotificationListenerService` for a real notification.

No camera, microphone, GPS, accelerometer or high-frequency sensor polling is enabled by default.

The persistent connection uses Android's `connectedDevice` foreground-service type rather than `dataSync`. Android 15 limits `dataSync` foreground services to six hours per 24 hours, whereas this app is maintaining an ongoing network interaction with an external Raspberry Pi service.

## Phone notification privacy

Notification access is optional and must be granted manually from Android Settings.

The notification listener does not require NekoSuneAI to become the default SMS application. For ordinary SMS/RCS messages, Samsung Messages or Google Messages normally posts a notification whose title is the sender/contact and whose body contains the message preview. NekoSuneAI can forward that notification metadata.

This also means the feature works for WhatsApp, Discord and other messaging applications that post normal Android notifications.

Do not add `READ_SMS`/`RECEIVE_SMS` unless a future use case genuinely requires raw SMS access. Notification access is much less invasive for this assistant use case.

## Find My Phone

When the Pi sends `FIND_PHONE`, the Android app:

1. starts the Find Phone foreground service;
2. stores the current ringtone volume;
3. raises the ringtone stream to its maximum;
4. plays the device's normal ringtone in a loop;
5. shows a persistent notification with a STOP button.

When the user taps STOP, or NekoSuneAI receives a phrase such as `stop ringing my phone`, the previous ringtone volume is restored.

## VRM avatars

Open NekoSuneAI Companion and enter a direct HTTPS URL to a `.vrm` model, then press **Load VRM**.

The initial renderer is deliberately lightweight. It caps renderer pixel ratio to 1.5 and only runs the WebGL view while the Android activity is visible. The always-connected background companion does not render the avatar, which prevents the VRM renderer from heating the phone while it is in a pocket or the screen is off.

The current renderer loads Three.js and `@pixiv/three-vrm` from jsDelivr. A later offline build can vendor those JavaScript modules inside the APK.

## Pi API

All endpoints use the existing `WEB_DASHBOARD_TOKEN` through the `X-Neko-Token` header.

- `POST /api/android/heartbeat`
- `POST /api/android/notification`
- `POST /api/android/command`
- `GET /api/android/devices`
- `GET /api/android/notifications`
- `GET /api/android/commands` (long poll)

Do not expose the raw Pi dashboard port directly to the public Internet. Prefer HTTPS through Tailscale, a VPN, or an authenticated reverse proxy/tunnel.

## Build

From a machine with Android SDK + Java 17:

```bash
gradle -p android assembleDebug
```

GitHub Actions also builds `android/app/build/outputs/apk/debug/app-debug.apk` and uploads it as the `NekoSuneAI-Android-debug` artifact.

## Android permissions

The current app uses:

- `INTERNET`
- `ACCESS_NETWORK_STATE`
- `CHANGE_NETWORK_STATE`
- `POST_NOTIFICATIONS`
- `FOREGROUND_SERVICE`
- `FOREGROUND_SERVICE_CONNECTED_DEVICE`
- `FOREGROUND_SERVICE_MEDIA_PLAYBACK`
- `WAKE_LOCK`
- `VIBRATE`
- `MODIFY_AUDIO_SETTINGS`

Notification access is a special user-granted service permission opened through Android Settings rather than a normal runtime permission.

## Useful next modules

The architecture is ready for additional opt-in modules such as device location, lost-phone map support, Wi-Fi/home presence, clipboard send-to-PC, file/photo transfer, call-state alerts, calendar reminders, alarms/timers, smart-home controls, phone-to-Pi voice commands, media controls, and multiple Android devices.

Location, microphone, camera, contacts, call logs, and raw SMS should remain separate opt-in permission groups rather than being silently enabled by the base companion.

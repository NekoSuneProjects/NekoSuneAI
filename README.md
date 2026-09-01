# NekoSuneAI Android Companion

[![Android APK Build](https://img.shields.io/badge/build-android--apk-3DDC84)](.github/workflows/android-companion.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPL_v3-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-see-VERSION-violet)](VERSION)

Native Android companion app that pairs with a Pi/Docker-hosted NekoSuneAI
instance: remote chat/voice, telemetry, notification forwarding, Find My
Phone, scam-call screening, wake word, and a shared VRM avatar. This build is
intentionally minimal: it contains only the files needed to build the Android
APK, trimmed from the wider NekoSuneAI project.

## What's here

- `android/` — the Gradle/Kotlin Android project
- `docs/ANDROID_COMPANION.md` — feature set and permissions
- `docs/ANDROID_MOBILE.md` — pairing with a Pi/Docker NekoSuneAI instance
- `test/test_android_companion_source.py` — source-level checks against the
  Kotlin/manifest files (no Python app dependencies)
- `.github/workflows/android-companion.yml` — CI build/release workflow

## Building

```bash
gradle -p android --no-daemon assembleDebug
```

The debug APK is produced at
`android/app/build/outputs/apk/debug/app-debug.apk`.

Requires JDK 17, Android SDK 36, and build-tools 35.0.0 (see the CI workflow
for exact setup steps).

## Tests

```
pytest test/test_android_companion_source.py
```

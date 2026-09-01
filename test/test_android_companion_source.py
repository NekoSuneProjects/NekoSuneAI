from pathlib import Path


MAIN = Path("android/app/src/main/java/co/uk/nekosuneprojects/nekosuneai/MainActivity.kt")
SCAM_SETTINGS = Path("android/app/src/main/java/co/uk/nekosuneprojects/nekosuneai/ScamCallSettingsActivity.kt")
MANIFEST = Path("android/app/src/main/AndroidManifest.xml")


def test_call_protection_is_visible_and_requests_android_screening_role():
    main = MAIN.read_text(encoding="utf-8")
    settings = SCAM_SETTINGS.read_text(encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")
    assert 'navButton("Protect"' in main
    assert 'primaryButton("Allow caller-number screening"' in main
    assert "RoleManager.ROLE_CALL_SCREENING" in main
    assert 'getBooleanExtra("enable_now", false)' in settings
    assert "android.telecom.CallScreeningService" in manifest
    assert "android.permission.BIND_SCREENING_SERVICE" in manifest


def test_recent_server_tools_have_mobile_shortcuts():
    main = MAIN.read_text(encoding="utf-8")
    assert 'navButton("Tools"' in main
    for command in (
        "house status briefing",
        "weather station report",
        "news briefing",
        "home timeline last 24 hours",
        "streaming status",
        "check a stream for ",
        "stop all game input",
    ):
        assert command in main


def test_android_version_is_bumped_for_updated_apk():
    gradle = Path("android/app/build.gradle.kts").read_text(encoding="utf-8")
    assert "versionCode = 2" in gradle
    assert 'versionName = "0.2.0"' in gradle

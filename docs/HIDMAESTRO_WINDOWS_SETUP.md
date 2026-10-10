# HIDMaestro controller backend (optional)

NekoSuneAI Windows Gaming Node uses HIDMaestro as its **optional** virtual controller backend instead of `vgamepad`/ViGEmBus. BlueStacks / Disney Solitaire uses ADB and does **not** need HIDMaestro.

## Prerequisites (your Windows PC only)

1. Install .NET 10 SDK.
2. Follow the official HIDMaestro instructions at https://github.com/hifihedgehog/HIDMaestro to build the signed UMDF driver and HIDMaestro.Core SDK. Driver setup requires local elevation and your approval. Do **not** attempt to install it in GitHub Actions.
3. With the built `HIDMaestro.Core.dll` available, compile the NekoSuneAI companion from the repository root:

```powershell
$env:HIDMAESTRO_SDK_PATH = "C:\Path\To\HIDMaestro.Core.dll"
dotnet build tools\hidmaestro-bridge\HIDMaestroBridge.csproj -c Release
$env:NEKOSUNE_HIDMAESTRO_BRIDGE = (Resolve-Path tools\hidmaestro-bridge\bin\Release\net10.0-windows\HIDMaestroBridge.exe).Path
```

This companion launches *only* when you select a game profile with `allow_controller=true`; it accepts an allowlisted local JSON-lines protocol for buttons, sticks, triggers and reset. It does not offer remote shell commands, keyboard access or controller-driver installation. It exits with the node and resets the gamepad state on graceful exit.

## CI / release

The normal Windows EXE build does not download, build or install the HIDMaestro driver or SDK; controller emulation requires the separate locally built sidecar. This separation prevents unattended driver prompts. Users who only need BlueStacks/ADB do not need any controller driver.

## Status

The HIDMaestro sidecar needs real Windows hardware validation for Xbox and DualShock profiles, and the upstream driver is privileged software. Never enable controller game input without explicit user approval and an allowlisted single-player game profile.

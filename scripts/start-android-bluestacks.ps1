param(
  [Parameter(Mandatory=$true)][string]$MainUrl,
  [string]$NodeId = "android-bluestacks",
  [string]$PairingId = "",
  [string]$PairingCode = "",
  [string]$DeviceSerial = "127.0.0.1:5555",
  [string]$LanHost = "0.0.0.0",
  [int]$LanPort = 8765
)
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))
$py = (Get-Command py -ErrorAction SilentlyContinue)
if ($py) { $python = "py" } else { $python = "python" }
& $python -m pip install -r requirements-android-gameplay.txt
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed" }
& adb connect $DeviceSerial
if ($LASTEXITCODE -ne 0) { throw "Could not connect ADB to BlueStacks; enable ADB in BlueStacks settings" }
& adb -s $DeviceSerial shell pm path com.superplaystudios.disneysolitairedreams
if ($LASTEXITCODE -ne 0) { throw "Disney Solitaire is not installed on this BlueStacks instance" }
$secretFile = ".android-lan-status-secret"
if (!(Test-Path $secretFile)) {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
  [IO.File]::WriteAllText((Join-Path (Get-Location) $secretFile),
    [Convert]::ToHexString($bytes))
}
Write-Host "PiProxy LAN secret: $(Get-Content $secretFile)"
Write-Host "Configure your Raspberry Pi allowlist using the PC's private LAN IP, port $LanPort, and that secret."
Write-Host "Do not forward the LAN status port to the internet."
$workerArgs = @(
  "-m", "nekosuneai.android_gameplay.main_bridge",
  "--server", $MainUrl,
  "--node-id", $NodeId,
  "--device-serial", $DeviceSerial,
  "--allow-package", "com.superplaystudios.disneysolitairedreams",
  "--lan-status-host", $LanHost,
  "--lan-status-port", "$LanPort",
  "--lan-status-token-file", $secretFile
)
if ($PairingId -and $PairingCode) {
  $workerArgs += @("--pairing-id", $PairingId, "--pairing-code", $PairingCode)
}
& $python @workerArgs

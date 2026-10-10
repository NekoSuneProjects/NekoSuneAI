param(
    [Parameter(Mandatory=$true)][string]$MainUrl,
    [string]$Serial = "127.0.0.1:5555",
    [string]$NodeId = "windows-android-bluestacks",
    [string]$PairingId = "",
    [string]$PairingCode = "",
    [int]$StatusPort = 8765,
    [switch]$EnablePiStatus
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = if (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { 'python' }
& $python -m pip install -r requirements-windows-android-fallback.txt
if ($LASTEXITCODE -ne 0) { throw 'Failed to install Windows Android fallback dependencies' }
if (!(Get-Command adb -ErrorAction SilentlyContinue)) {
    throw 'ADB not found. Install Android platform-tools and enable ADB in BlueStacks.'
}
& adb connect $Serial
if ($LASTEXITCODE -ne 0) { throw 'BlueStacks ADB connection failed' }
$installed = & adb -s $Serial shell pm path com.superplaystudios.disneysolitairedreams
if ($LASTEXITCODE -ne 0 -or !$installed) {
    throw 'Disney Solitaire is not installed in the selected BlueStacks instance'
}
$arguments = @('-m','nekosuneai.android_gameplay.main_bridge','--server',$MainUrl,
    '--node-id',$NodeId,'--device-serial',$Serial,
    '--allow-package','com.superplaystudios.disneysolitairedreams',
    '--token-file',(Join-Path $root '.windows-android-node-token'),
    '--state-file',(Join-Path $root '.windows-android-node-state.json'))
if ($PairingId -and $PairingCode) {
    $arguments += @('--pairing-id',$PairingId,'--pairing-code',$PairingCode)
}
if ($EnablePiStatus) {
    $secretPath = Join-Path $root '.windows-android-lan-token'
    if (!(Test-Path $secretPath)) {
        $randomBytes = New-Object byte[] 32
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($randomBytes) } finally { $rng.Dispose() }
        [IO.File]::WriteAllText($secretPath, ([BitConverter]::ToString($randomBytes) -replace '-', ''))
    }
    $arguments += @('--lan-status-host','0.0.0.0','--lan-status-port',"$StatusPort",
                    '--lan-status-token-file',$secretPath)
    Write-Host 'PiProxy status enabled. Configure the Pi with the Windows PC LAN IP and secret from:' $secretPath
} else {
    Write-Host 'Direct Windows -> Main fallback enabled; PiProxy is not required.'
}
Write-Host 'Starting Android worker for Disney Solitaire; Ctrl+C stops the worker.'
& $python @arguments

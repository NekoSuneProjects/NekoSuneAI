; NekoSuneAI Windows installer (Inno Setup).
;
; Built from the PyInstaller onedir output (see NekoSuneAI.spec at the repo
; root) — this script does not invoke PyInstaller itself, it packages
; whatever's already in <repo>\dist\NekoSuneAI.
;
; Usage (from the repo root, after `pyinstaller NekoSuneAI.spec`):
;   iscc /DAppVersion=1.1.9 packaging\windows\nekosuneai.iss
;
; Installs per-user (no admin elevation) under {localappdata}\NekoSuneAI,
; NOT Program Files — deliberately: this app writes its own data (SQLite
; database, songs, audio, downloaded models) next to the executable
; (nekosuneai/paths.py's ROOT_DIR, resolved to the exe's own directory when
; frozen — see the 1.1.9 changelog entry), and Program Files is not
; user-writable without elevation. A per-user install directory keeps that
; working with zero extra permissions plumbing.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "NekoSuneAI"
#define AppPublisher "NekoSuneProjects"
#define AppURL "https://github.com/NekoSuneProjects/NekoSuneAI"
#define DistDir "..\..\dist\NekoSuneAI"

[Setup]
; Fixed, never change: lets Inno Setup recognize "this is an upgrade of the
; same app" across versions (offers Modify/Repair/Uninstall automatically
; instead of installing a confusing second copy).
AppId={{6C7B6E6E-6E6B-4F53-9F1D-3E9C2A1E7B21}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
DefaultDirName={localappdata}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist-installer
OutputBaseFilename=NekoSuneAI-Setup-{#AppVersion}
SetupIconFile=..\..\data\logo.ico
UninstallDisplayIcon={app}\NekoSuneAI.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\NekoSuneAI.exe"; Parameters: "--gui"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\NekoSuneAI.exe"; Parameters: "--gui"; Tasks: desktopicon

[Run]
Filename: "{app}\NekoSuneAI.exe"; Parameters: "--gui"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The app's own data (SQLite db, songs, audio) lives under {app} too, next to
; the exe — remove it on uninstall so nothing is left behind. Users who want
; to keep their profiles/history should back up {app}\data before uninstalling.
Type: filesandordirs; Name: "{app}"

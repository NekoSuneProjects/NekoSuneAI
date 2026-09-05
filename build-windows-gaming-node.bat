@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo === NekoSuneAI Windows Gaming Node - local build ===

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3.12"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PY=python"
    ) else (
        echo [ERROR] Python was not found on PATH. Install Python 3.12 and try again.
        exit /b 1
    )
)

echo.
echo [1/4] Installing build dependencies (this can take a while on first run)...
set "VGAMEPAD_SKIP_VIGEMBUS_INSTALL=true"
%PY% -m pip install --disable-pip-version-check -r requirements-windows-gaming-node.txt
if errorlevel 1 (
    echo [ERROR] Dependency install failed.
    exit /b 1
)

echo.
echo [2/4] Verifying package imports...
%PY% -c "import nekosuneai; import nekosuneai.windows_gaming_agent; import vgamepad; print('Windows Gaming Node imports OK')"
if errorlevel 1 (
    echo [ERROR] Import check failed.
    exit /b 1
)

echo.
echo [3/4] Building standalone GUI EXE with PyInstaller...
%PY% -m PyInstaller --noconfirm --clean NekoSuneAI-Windows-Gaming-Node.spec
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    exit /b 1
)

if not exist dist\NekoSuneAI-Windows-Gaming-Node.exe (
    echo [ERROR] Build did not produce dist\NekoSuneAI-Windows-Gaming-Node.exe
    exit /b 1
)

echo.
echo [4/4] Packaging release folder...
set /p VERSION=<VERSION
set "RELEASE_DIR=release\NekoSuneAI-Windows-Gaming-Node-%VERSION%"
if exist "%RELEASE_DIR%" rd /s /q "%RELEASE_DIR%"
mkdir "%RELEASE_DIR%"

copy /y dist\NekoSuneAI-Windows-Gaming-Node.exe "%RELEASE_DIR%\" >nul
copy /y config\windows-gaming-agent.example.json "%RELEASE_DIR%\windows-gaming-agent.example.json" >nul
copy /y docs\GAME_SKILLS_AND_REMOTE_PLAY.md "%RELEASE_DIR%\GAME_SKILLS_AND_REMOTE_PLAY.md" >nul
if exist docs\WINDOWS_MEDIA_AND_VRCHAT.md copy /y docs\WINDOWS_MEDIA_AND_VRCHAT.md "%RELEASE_DIR%\WINDOWS_MEDIA_AND_VRCHAT.md" >nul
xcopy /e /i /y game-skills "%RELEASE_DIR%\game-skills" >nul

(
  echo NekoSuneAI Windows Gaming Node
  echo.
  echo Launch NekoSuneAI-Windows-Gaming-Node.exe.
  echo.
  echo The Windows app provides a GUI for:
  echo - NekoSuneAI server address setup
  echo - LAN discovery of common NekoSuneAI hostnames
  echo - pairing ID + pairing code registration
  echo - local device-token storage
  echo - game / Xbox Remote Play / PlayStation Remote Play profile selection
  echo - start/stop status for the Windows Gaming Node
  echo.
  echo No CLI arguments are required for normal setup.
  echo.
  echo Virtual Xbox 360 / DualShock 4 controller support uses vgamepad and
  echo requires ViGEmBus to be installed on this PC ^(https://github.com/ViGEm/ViGEmBus/releases^).
) > "%RELEASE_DIR%\README-WINDOWS-GAMING-NODE.txt"

echo.
echo === Build complete ===
echo EXE:     dist\NekoSuneAI-Windows-Gaming-Node.exe
echo Release: %RELEASE_DIR%
endlocal

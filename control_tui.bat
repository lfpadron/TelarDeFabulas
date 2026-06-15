@echo off
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo uv no esta instalado o no esta en PATH.
    echo Instala uv desde: https://docs.astral.sh/uv/getting-started/installation/
    exit /b 1
)

uv run --only-group tui python tools\control_tui.py %*
endlocal

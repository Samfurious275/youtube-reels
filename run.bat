@echo off
REM Command line. First run installs everything it needs, then it just passes
REM your arguments to reels.py.
setlocal
cd /d "%~dp0"

where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo Installing ffmpeg...
  winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
  if errorlevel 1 (
    echo.
    echo Could not install ffmpeg automatically.
    echo Get it from https://ffmpeg.org/download.html and put ffmpeg.exe on your PATH.
    pause
    exit /b 1
  )
  echo.
  echo ffmpeg was just installed. Close this window, open a NEW one, and run this again
  echo so that Windows picks up the changed PATH.
  pause
  exit /b 0
)

where yt-dlp >nul 2>&1
if errorlevel 1 (
  echo Installing yt-dlp...
  winget install --id yt-dlp.yt-dlp -e --accept-source-agreements --accept-package-agreements
)

if not exist ".venv\Scripts\python.exe" (
  REM torch 2.2.2 has no Windows wheel for python 3.12+, so pin to 3.11
  py -3.11 --version >nul 2>&1
  if errorlevel 1 (
    echo.
    echo Python 3.11 is required but was not found.
    echo Install it from https://www.python.org/downloads/release/python-3119/
    echo and tick "Add python.exe to PATH" in the installer, then run this again.
    pause
    exit /b 1
  )
  echo Creating the environment. This takes a few minutes the first time...
  py -3.11 -m venv .venv || goto :failed
  .venv\Scripts\python.exe -m pip install --upgrade pip || goto :failed
  .venv\Scripts\python.exe -m pip install -r requirements.txt || goto :failed
)

.venv\Scripts\python.exe reels.py %*
if errorlevel 1 pause
exit /b 0

:failed
echo.
echo Setup failed. The messages above say why.
pause
exit /b 1

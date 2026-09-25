#!/bin/bash
# Command line. First run installs everything it needs, then it just passes your
# arguments to reels.py.
set -e
cd "$(dirname "$0")"

# --- ffmpeg and yt-dlp ------------------------------------------------------
for tool in ffmpeg yt-dlp; do
  command -v "$tool" >/dev/null && continue
  if command -v brew >/dev/null; then
    brew install "$tool"
  elif command -v apt >/dev/null; then
    if [ "$tool" = ffmpeg ]; then
      sudo apt update && sudo apt install -y ffmpeg fonts-dejavu-core
    else
      sudo apt update && sudo apt install -y yt-dlp || pip install --user yt-dlp
    fi
  else
    echo "Please install $tool, then run this again."
    exit 1
  fi
done

# --- python 3.11 ------------------------------------------------------------
# torch 2.2.2 is the newest build for Intel Macs and has no wheels past 3.11,
# so the venv has to be built with that interpreter specifically.
find_python() {
  for c in python3.11 /usr/local/opt/python@3.11/bin/python3.11 \
           /opt/homebrew/opt/python@3.11/bin/python3.11 \
           /usr/bin/python3.11; do
    command -v "$c" >/dev/null 2>&1 && { echo "$c"; return 0; }
  done
  return 1
}

if [ ! -x .venv/bin/python ]; then
  PY="$(find_python)" || {
    if command -v brew >/dev/null; then
      brew install python@3.11
      PY="$(find_python)" || { echo "python@3.11 installed but not found."; exit 1; }
    else
      echo "Python 3.11 is required but was not found."
      echo "  Debian/Ubuntu:  sudo apt install python3.11 python3.11-venv"
      echo "  or add the deadsnakes PPA if your release does not carry it:"
      echo "    sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt update"
      exit 1
    fi
  }
  echo "Building the environment with $PY. This takes a while the first time..."
  "$PY" -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi

exec .venv/bin/python reels.py "$@"

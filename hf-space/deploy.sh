#!/bin/bash
# Publish this project as a Hugging Face Space, so other people can use it from
# a link without installing anything.
#
#   ./hf-space/deploy.sh your-username/reel-maker
#
# Create the Space first at https://huggingface.co/new-space (pick the Docker
# SDK), then run this. It copies the parts the Space needs -- the pipeline, the
# page, and the pinned dependency list -- so there is never a second copy of
# reels.py in this repo drifting out of step with the real one.
set -e
cd "$(dirname "$0")"

SPACE="$1"
if [ -z "$SPACE" ]; then
  echo "usage: ./hf-space/deploy.sh <your-username>/<space-name>"
  exit 1
fi

command -v git >/dev/null || { echo "git is required."; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Cloning https://huggingface.co/spaces/$SPACE ..."
echo "If it asks for a password, paste an access token with write permission"
echo "from https://huggingface.co/settings/tokens"
git clone "https://huggingface.co/spaces/$SPACE" "$TMP"

cp ../reels.py ../serve.py ../requirements.txt Dockerfile app.py README.md "$TMP/"

cd "$TMP"
git add -A
if git diff --cached --quiet; then
  echo "Nothing changed since the last deploy."
  exit 0
fi
git commit -m "Deploy reel maker"
git push

echo
echo "Done. Your Space is building at:"
echo "    https://huggingface.co/spaces/$SPACE"
echo "The first build takes several minutes. Share that link with anyone."

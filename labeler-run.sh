#!/usr/bin/env bash
# Run the labeler with the usual settings: video FtU4MuksCzE, 3 fps strip, worst quality, port 8765.
# Anything you pass is added to ./labeler.sh, and a leading video URL or id replaces the default:
#   ./labeler-run.sh                 # FtU4MuksCzE
#   ./labeler-run.sh Ij427pW96aI     # another video
#   ./labeler-run.sh --port 8800     # same video, another port
set -euo pipefail
cd "$(dirname "$0")"

video="FtU4MuksCzE"
if [[ $# -gt 0 && "$1" != -* ]]; then
  video="$1"
  shift
fi
exec ./labeler.sh "$video" --fps 3 --port 8765 "$@"

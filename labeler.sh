#!/usr/bin/env bash
# Start the frame labeler dev server; it restarts when a Python file under tools/labeling/ changes
# (refresh the browser tab after a restart; page.html edits need only a refresh).
#
#   ./labeler.sh <youtube-url-or-id> [--fps N] [--format-id ID] [--port N] [--proxy URL]
#
# Needs the labeling extra: pip install -e ".[labeling]"
set -euo pipefail
cd "$(dirname "$0")"

usage() { sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

source_arg=""
port=8765
while [[ $# -gt 0 ]]; do
  case "$1" in
    --fps)       export LABELER_FPS="${2:?--fps needs a value}"; shift 2 ;;
    --format-id) export LABELER_FORMAT_ID="${2:?--format-id needs a value}"; shift 2 ;;
    --proxy)     export LABELER_PROXY="${2:?--proxy needs a value}"; shift 2 ;;
    --port)      port="${2:?--port needs a value}"; shift 2 ;;
    -h|--help)   usage 0 ;;
    -*)          echo "Unknown option: $1" >&2; usage 1 ;;
    *)           [[ -z "$source_arg" ]] || { echo "Only one video allowed" >&2; usage 1; }
                 source_arg="$1"; shift ;;
  esac
done
[[ -n "$source_arg" ]] || { echo "Missing the YouTube URL or id" >&2; usage 1; }
export LABELER_SOURCE="$source_arg"

python=".venv/bin/python"
[[ -x "$python" ]] || python="python3"
exec "$python" -m flask --app tools.labeling.wsgi:create_app run --debug --host 127.0.0.1 --port "$port"

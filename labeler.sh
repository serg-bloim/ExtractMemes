#!/usr/bin/env bash
# Start the frame labeler dev server; it restarts when a Python file under tools/labeling/ or
# src/extract_memes/ changes, including a new criterion file added there
# (refresh the browser tab after a restart; page.html edits need only a refresh).
#
#   ./labeler.sh [youtube-url-or-id] [--format-id ID] [--port N] [--proxy URL]
#
# Without a video, the page opens on a field where you enter one.
#
# Needs the labeling extra: pip install -e ".[labeling]"
set -euo pipefail
cd "$(dirname "$0")"

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

source_arg=""
port=8765
while [[ $# -gt 0 ]]; do
  case "$1" in
    --format-id) export LABELER_FORMAT_ID="${2:?--format-id needs a value}"; shift 2 ;;
    --proxy)     export LABELER_PROXY="${2:?--proxy needs a value}"; shift 2 ;;
    --port)      port="${2:?--port needs a value}"; shift 2 ;;
    -h|--help)   usage 0 ;;
    -*)          echo "Unknown option: $1" >&2; usage 1 ;;
    *)           [[ -z "$source_arg" ]] || { echo "Only one video allowed" >&2; usage 1; }
                 source_arg="$1"; shift ;;
  esac
done
[[ -z "$source_arg" ]] || export LABELER_SOURCE="$source_arg"

python=".venv/bin/python"
[[ -x "$python" ]] || python="python3"
# watchfiles restarts Flask whenever a Python file under src/extract_memes (the criteria and the
# classifiers) or tools/labeling changes, new files included, which Flask's own reloader doesn't
# notice (a criterion added as a new file is picked up).
exec "$python" -m watchfiles --filter python \
  "$python -m flask --app tools.labeling.wsgi:create_app run --debug --no-reload --host 127.0.0.1 --port $port" \
  src/extract_memes tools/labeling

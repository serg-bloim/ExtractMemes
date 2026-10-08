#!/usr/bin/env bash
# Store every scene of one or more videos, with the stats of every criterion, in the scene database
# (data/datasets/scene_analysis/scene_analysis.yaml). The format is the dataset's if the video has
# one, else --format-id, else the labeler's preselection. Videos are cached in .runtime/downloads/.
#
#   ./populate_scenes.sh <video-id-or-url>... [--format-id ID] [--no-prompt] [--proxy URL] [--db FILE]
#
# For a video with no dataset and no --format-id, in a terminal, it lists the formats (downloaded ones
# highlighted, else the labeler's default) and lets you pick with the up/down arrows (PgUp/PgDn, Home/End,
# Enter to select, q to cancel); --no-prompt takes the default.
# Without a video it asks for one when run in a terminal.
# Prints the errors of each video and exits non-zero if any video had one.
#
# Needs the labeling extra: pip install -e ".[labeling]"
set -euo pipefail
cd "$(dirname "$0")"

usage() { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

videos=()
options=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --format-id|--proxy|--db) options+=("$1" "${2:?$1 needs a value}"); shift 2 ;;
    --no-prompt) options+=("$1"); shift ;;
    -h|--help)   usage 0 ;;
    -*)          echo "Unknown option: $1" >&2; usage 1 ;;
    *)           videos+=("$1"); shift ;;
  esac
done
if [[ ${#videos[@]} -eq 0 ]]; then
  [[ -t 0 ]] || { echo "Give at least one video" >&2; usage 1; }
  read -r -p "Video id or URL (several separated by spaces): " -a videos || true
  [[ ${#videos[@]} -gt 0 ]] || { echo "No video given" >&2; exit 1; }
fi

python=".venv/bin/python"
[[ -x "$python" ]] || python="python3"
status=0
for video in "${videos[@]}"; do
  "$python" -m tools.scene_analysis populate "$video" ${options[@]+"${options[@]}"} || status=1
done
exit $status

#!/usr/bin/env bash
# Commit and push the data-branch checkout, optionally recording video statuses.
#
# usage: push-data.sh <commit message> [<status> <ids-file>]
#
# Two workflows push to the data branch, so a push can be rejected. The changes made during the run
# (images, caches) are committed once; every attempt re-applies them on top of the latest data branch
# and then sets <status> for the ids in <ids-file> (a missing file sets none) on the freshly fetched
# status file, so the two workflows never conflict on it. Run from the repository root.
set -euo pipefail

message=$1
status=${2:-}
ids_file=${3:-}
processed_file=data-branch/processed_vids.txt

git -C data-branch config user.name "github-actions[bot]"
git -C data-branch config user.email "github-actions[bot]@users.noreply.github.com"

base=$(git -C data-branch rev-parse HEAD)
git -C data-branch add --sparse -A
if ! git -C data-branch diff --cached --quiet; then
  git -C data-branch commit -q -m "$message"
fi
mine=$(git -C data-branch rev-parse HEAD)

for attempt in 1 2 3 4 5; do
  git -C data-branch fetch -q --depth=1 origin data
  git -C data-branch checkout -q --detach origin/data
  if [ "$mine" != "$base" ]; then
    git -C data-branch cherry-pick "$base..$mine" >/dev/null
  fi
  if [ -n "$status" ]; then
    python -m extract_memes.playlist_watch set-status "$status" --ids-file "$ids_file" --processed-file "$processed_file"
    git -C data-branch add --sparse -A
    if ! git -C data-branch diff --cached --quiet; then
      git -C data-branch commit -q -m "Mark videos as $status"
    fi
  fi
  if [ "$(git -C data-branch rev-parse HEAD)" = "$(git -C data-branch rev-parse origin/data)" ]; then
    echo "Nothing to push"
    exit 0
  fi
  if git -C data-branch push -q origin HEAD:refs/heads/data; then
    exit 0
  fi
  echo "Push rejected (attempt $attempt), retrying"
  sleep $((attempt * 3))
done
echo "Could not push the data branch" >&2
exit 1

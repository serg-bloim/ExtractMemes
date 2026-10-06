#!/usr/bin/env bash
# Example: extract memes from a YouTube video, upload them to Telegram and post the timecodes.
# Edit the values below, then run: ./run_example.sh [video-url]
set -euo pipefail
cd "$(dirname "$0")"

VIDEO_URL="${1:-https://youtu.be/lx011zFYIGU}"

# --- Replace these ---
TELEGRAM_BOT_TOKEN="8519372255:AAFSayd__J5lzb6Pjmu403ow3GtVnZ8J064"   # from @BotFather
TELEGRAM_CHAT_ID="-1004467715581"                            # chat that receives the meme images
TELEGRAM_TIMECODES_CHAT_ID="-1009876543210"                  # chat that receives the timecodes
# EXTRACT_MEMES_PROXY="socks5h://127.0.0.1:1080"             # optional, for yt-dlp downloads
# ---------------------

export TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID TELEGRAM_TIMECODES_CHAT_ID
[ -n "${EXTRACT_MEMES_PROXY:-}" ] && export EXTRACT_MEMES_PROXY

[ -f .venv/bin/activate ] && source .venv/bin/activate

extract-memes "$VIDEO_URL" \
  --classifier heuristic \
  --upload-to telegram \
  --send-timecodes-to telegram \
  --save-timecodes \
  --save-low-res --save-high-res \
  --downloads-dir .runtime/downloads \
  --runtime-dir .runtime

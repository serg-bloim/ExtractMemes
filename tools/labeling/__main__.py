"""Label the memes in a YouTube video: `python -m tools.labeling <url-or-video-id>` from the project root.

This is the plain launcher. For a server that reloads when the sources change, use ./labeler.sh.
"""

import argparse
import webbrowser

from .bootstrap import open_labeler
from .server import create_flask_app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tools.labeling", description=__doc__)
    parser.add_argument("source", help="YouTube URL or video id")
    parser.add_argument("--fps", type=float, default=3.0, help="scan rate the strip shows (default: %(default)s)")
    parser.add_argument("--format-id", help="yt-dlp format to label when there is no dataset yet (default: worst)")
    parser.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (default: %(default)s)")
    parser.add_argument("--proxy", help="proxy for yt-dlp")
    parser.add_argument("--open", action="store_true", help="open the page in the default browser")
    args = parser.parse_args(argv)

    labeler = open_labeler(args.source, fps=args.fps, format_id=args.format_id, proxy=args.proxy)
    address = f"http://127.0.0.1:{args.port}/"
    print(f"Labeler ready: {address}  (Ctrl+C to stop)")
    if args.open:
        webbrowser.open(address)
    try:
        create_flask_app(labeler).run(host="127.0.0.1", port=args.port, threaded=True)
    finally:
        labeler.close()


if __name__ == "__main__":
    main()

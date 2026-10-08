"""Label the memes in a YouTube video: `python -m tools.labeling <url-or-video-id>` from the project root.

This is the plain launcher. For a server that reloads when the sources change, use ./labeler.sh.
"""

import argparse
import webbrowser

from .bootstrap import make_workspace
from .server import create_flask_app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tools.labeling", description=__doc__)
    parser.add_argument("source", nargs="?", help="YouTube URL or video id to open at start (or choose one in the page)")
    parser.add_argument("--format-id", help="yt-dlp format to label when there is no dataset yet (default: worst)")
    parser.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (default: %(default)s)")
    parser.add_argument("--proxy", help="proxy for yt-dlp")
    parser.add_argument("--open", action="store_true", help="open the page in the default browser")
    args = parser.parse_args(argv)

    workspace = make_workspace(args.source, format_id=args.format_id, proxy=args.proxy)
    address = f"http://127.0.0.1:{args.port}/"
    print(f"Labeler ready: {address}  (Ctrl+C to stop)")
    if args.open:
        webbrowser.open(address)
    create_flask_app(workspace).run(host="127.0.0.1", port=args.port, threaded=True)


if __name__ == "__main__":
    main()

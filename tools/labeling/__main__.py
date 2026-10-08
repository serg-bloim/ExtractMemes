"""Label the memes in a YouTube video: `python -m tools.labeling <url-or-video-id>` from the project root.

This is the plain launcher. For a server that reloads when the sources change, use ./labeler.sh.
"""

import argparse
import webbrowser

from .bootstrap import make_workspace
from .network import announce, urls
from .server import create_flask_app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tools.labeling", description=__doc__)
    parser.add_argument("source", nargs="?", help="YouTube URL or video id to open at start (or choose one in the page)")
    parser.add_argument("--format-id", help="yt-dlp format to label when there is no dataset yet (default: worst)")
    parser.add_argument("--port", type=int, default=8765, help="port, on every address (default: %(default)s)")
    parser.add_argument("--proxy", help="proxy for yt-dlp")
    parser.add_argument("--open", action="store_true", help="open the page in the default browser")
    args = parser.parse_args(argv)

    workspace = make_workspace(args.source, format_id=args.format_id, proxy=args.proxy)
    print(f"{announce(args.port)}  (Ctrl+C to stop)")
    if args.open:
        webbrowser.open(urls(args.port)[0])
    create_flask_app(workspace).run(host="0.0.0.0", port=args.port, threaded=True)


if __name__ == "__main__":
    main()

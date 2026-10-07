"""Label the memes in a YouTube video: `python -m tools.labeling <url-or-video-id>` from the project root."""

import argparse
import webbrowser

from extract_memes.downloader import FORMAT_SELECTORS

from . import dataset as dataset_module
from .dataset import Dataset
from .index import CACHE_ROOT, build
from .server import LabelerApp, serve


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tools.labeling", description=__doc__)
    parser.add_argument("source", help="YouTube URL or video id")
    parser.add_argument("--fps", type=float, default=3.0, help="scan rate the strip shows (default: %(default)s)")
    parser.add_argument("--format-id", help="yt-dlp format to label when there is no dataset yet (default: worst)")
    parser.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (default: %(default)s)")
    parser.add_argument("--proxy", help="proxy for yt-dlp")
    parser.add_argument("--open", action="store_true", help="open the page in the default browser")
    args = parser.parse_args(argv)

    video_id = dataset_module.video_id_from(args.source)
    dataset_file = dataset_module.dataset_path(video_id)
    if dataset_file.is_file():
        dataset = dataset_module.load(dataset_file)
        print(f"Loaded {dataset_file} ({len(dataset.memes)} marks)")
        video_path = dataset_module.ensure_video(dataset, proxy=args.proxy)
    else:
        url = args.source if "/" in args.source else f"https://www.youtube.com/watch?v={video_id}"
        video_path, video = dataset_module.download_format(
            url, args.format_id or FORMAT_SELECTORS["worst"], proxy=args.proxy
        )
        dataset = Dataset(video=video)
        print(f"No dataset yet; {dataset_file} is created on the first mark (format {video.format_id})")

    cache_dir = CACHE_ROOT / f"{dataset.video.id}_{dataset.video.format_id}"
    index = build(video_path, cache_dir, fps=args.fps)
    app = LabelerApp(dataset, dataset_file, index, video_path)
    server = serve(app, args.port)
    address = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Labeler ready: {address}  (Ctrl+C to stop)")
    if args.open:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()


if __name__ == "__main__":
    main()

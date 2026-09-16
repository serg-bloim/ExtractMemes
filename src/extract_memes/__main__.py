"""Command-line entrypoint for ExtractMemes."""

import argparse


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="extract-memes",
        description=(
            "Extract meme images from a YouTube video known to contain them: "
            "download the video, extract frames, classify meme frames, and "
            "save them as standalone image files."
        ),
    )


def main() -> None:
    parser = build_parser()
    parser.parse_args()


if __name__ == "__main__":
    main()

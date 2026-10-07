"""Flask app factory for `flask --app tools.labeling.wsgi:create_app run --debug` (see labeler.sh).

The video and options come from environment variables, because `flask run` has no way to pass
them to a factory: LABELER_SOURCE (required), LABELER_FPS, LABELER_FORMAT_ID, LABELER_PROXY.
"""

import os

from flask import Flask

from .bootstrap import open_labeler
from .server import create_flask_app


def create_app() -> Flask:
    source = os.environ.get("LABELER_SOURCE")
    if not source:
        raise SystemExit("Set LABELER_SOURCE to a YouTube URL or id (or start it with ./labeler.sh)")
    labeler = open_labeler(
        source,
        fps=float(os.environ.get("LABELER_FPS", "3.0")),
        format_id=os.environ.get("LABELER_FORMAT_ID") or None,
        proxy=os.environ.get("LABELER_PROXY") or None,
    )
    return create_flask_app(labeler)

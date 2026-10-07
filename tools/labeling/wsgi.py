"""Flask app factory for `flask --app tools.labeling.wsgi:create_app run --debug` (see labeler.sh).

The options come from environment variables, because `flask run` has no way to pass them to a
factory: LABELER_SOURCE (a YouTube URL or id to open at start; optional, the page can open one),
LABELER_FPS, LABELER_FORMAT_ID, LABELER_PROXY.
"""

import os

from flask import Flask

from .bootstrap import make_workspace
from .server import create_flask_app


def create_app() -> Flask:
    workspace = make_workspace(
        source=os.environ.get("LABELER_SOURCE") or None,
        fps=float(os.environ.get("LABELER_FPS", "3.0")),
        format_id=os.environ.get("LABELER_FORMAT_ID") or None,
        proxy=os.environ.get("LABELER_PROXY") or None,
    )
    return create_flask_app(workspace)

"""Get from a YouTube URL or id to a ready `LabelerApp`: dataset, video file and cached index."""

from collections.abc import Callable

from extract_memes.downloader import FORMAT_SELECTORS

from . import dataset as dataset_module
from .dataset import Dataset
from .index import CACHE_ROOT, build
from .server import LabelerApp
from .workspace import Workspace


def open_labeler(
    source: str,
    fps: float = 3.0,
    format_id: str | None = None,
    proxy: str | None = None,
    progress: Callable[[str, float | None], None] | None = None,
) -> LabelerApp:
    """Load the dataset for `source` (or start one), fetch its exact video and index it."""
    video_id = dataset_module.video_id_from(source)
    dataset_file = dataset_module.dataset_path(video_id)
    if dataset_file.is_file():
        dataset = dataset_module.load(dataset_file)
        print(f"Loaded {dataset_file} ({len(dataset.memes)} memes, {len(dataset.not_memes)} not-memes)")
        video_path = dataset_module.ensure_video(dataset, proxy=proxy, progress=progress)
    else:
        url = source if "/" in source else f"https://www.youtube.com/watch?v={video_id}"
        video_path, video = dataset_module.download_format(
            url, format_id or FORMAT_SELECTORS["worst"], proxy=proxy, progress=progress
        )
        dataset = Dataset(video=video)
        print(f"No dataset yet; {dataset_file} is created on the first mark (format {video.format_id})")

    cache_dir = CACHE_ROOT / f"{dataset.video.id}_{dataset.video.format_id}"
    index = build(video_path, cache_dir, fps=fps, progress=progress)
    return LabelerApp(dataset, dataset_file, index, video_path)


LAST_VIDEO = CACHE_ROOT / "last_video.txt"


def _remember(video_id: str) -> None:
    LAST_VIDEO.parent.mkdir(parents=True, exist_ok=True)
    LAST_VIDEO.write_text(video_id)


def _last_video() -> str | None:
    try:
        return LAST_VIDEO.read_text().strip() or None
    except OSError:
        return None


def make_workspace(
    source: str | None = None, fps: float = 3.0, format_id: str | None = None, proxy: str | None = None
) -> Workspace:
    """A workspace that opens videos with these options.

    `source` is loaded now when given; without one the video opened last time is reopened (so a
    reload of the dev server keeps the video) if it still loads, else the page asks for one.
    """

    def opener(src: str, chosen_format: str | None, progress) -> LabelerApp:
        if chosen_format:
            existing = dataset_module.dataset_path(dataset_module.video_id_from(src))
            if existing.is_file() and dataset_module.load(existing).video.format_id != chosen_format:
                raise dataset_module.DatasetError(
                    f"{existing} is labeled in format {dataset_module.load(existing).video.format_id}; "
                    f"it can't be opened in format {chosen_format}"
                )
        labeler = open_labeler(src, fps=fps, format_id=chosen_format or format_id, proxy=proxy, progress=progress)
        _remember(labeler.dataset.video.id)
        return labeler

    initial = None
    if source:
        initial = opener(source, None, None)
    elif (last := _last_video()) and dataset_module.dataset_path(last).is_file():
        try:
            initial = opener(last, None, None)
        except Exception as exc:  # fall back to the "open a video" page rather than not starting
            print(f"Could not reopen {last}: {exc}")
    return Workspace(
        opener, initial=initial, inspector=lambda url: dataset_module.fetch_video_info(url, proxy)
    )

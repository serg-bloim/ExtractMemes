"""Get from a YouTube URL or id to a ready `LabelerApp`: dataset, video file and cached index."""

from extract_memes.downloader import FORMAT_SELECTORS

from . import dataset as dataset_module
from .dataset import Dataset
from .index import CACHE_ROOT, build
from .server import LabelerApp


def open_labeler(
    source: str, fps: float = 3.0, format_id: str | None = None, proxy: str | None = None
) -> LabelerApp:
    """Load the dataset for `source` (or start one), fetch its exact video and index it."""
    video_id = dataset_module.video_id_from(source)
    dataset_file = dataset_module.dataset_path(video_id)
    if dataset_file.is_file():
        dataset = dataset_module.load(dataset_file)
        print(f"Loaded {dataset_file} ({len(dataset.memes)} memes, {len(dataset.not_memes)} not-memes)")
        video_path = dataset_module.ensure_video(dataset, proxy=proxy)
    else:
        url = source if "/" in source else f"https://www.youtube.com/watch?v={video_id}"
        video_path, video = dataset_module.download_format(
            url, format_id or FORMAT_SELECTORS["worst"], proxy=proxy
        )
        dataset = Dataset(video=video)
        print(f"No dataset yet; {dataset_file} is created on the first mark (format {video.format_id})")

    cache_dir = CACHE_ROOT / f"{dataset.video.id}_{dataset.video.format_id}"
    index = build(video_path, cache_dir, fps=fps)
    return LabelerApp(dataset, dataset_file, index, video_path)

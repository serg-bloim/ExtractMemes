"""Choose a video format interactively: list what the video offers, mark what is already downloaded."""

import sys
from collections.abc import Callable
from pathlib import Path

from tools.labeling import dataset as ds

_BOLD_GREEN, _BOLD_CYAN, _DIM, _RESET = "\033[1;32m", "\033[1;36m", "\033[2m", "\033[0m"


def downloaded_ids(video_id: str, formats: list[dict], downloads_dir: Path = ds.DOWNLOADS_DIR) -> set[str]:
    """Ids of the `formats` whose file is already in the download cache."""
    return {f["format_id"] for f in formats if ds.downloaded_path(video_id, f["format_id"], f["ext"], downloads_dir).is_file()}


def default_format(formats: list[dict], downloaded: set[str]) -> str:
    """What Enter picks: the labeler's preselection among the downloaded formats if any, else among all."""
    pool = [f for f in formats if f["format_id"] in downloaded] or formats
    return ds.preferred_format(pool)


def render(formats: list[dict], downloaded: set[str], default: str, color: bool = False) -> list[str]:
    """One line per format. Downloaded ones are highlighted; when none is, the default is."""
    highlight = downloaded or {default}
    lines = []
    for number, f in enumerate(formats, 1):
        size = f"{f['size'] / 1e6:.1f} MB" if f.get("size") else "? MB"
        fps = f"{f['fps']:g}fps" if f.get("fps") else "?fps"
        notes = [n for n, on in (("downloaded", f["format_id"] in downloaded), ("default", f["format_id"] == default)) if on]
        line = (f"{'►' if f['format_id'] == default else ' '} {number:>2}. id {f['format_id']:<6} {str(f.get('width')) + 'x' + str(f.get('height')):<9} "
                f"{fps:<8} {(f.get('vcodec') or '').split('.')[0]:<6} {size:>9}" + (f"  ({', '.join(notes)})" if notes else ""))
        if color:
            line = (_BOLD_GREEN if f["format_id"] in downloaded else _BOLD_CYAN if f["format_id"] in highlight else _DIM) \
                + line + _RESET
        lines.append(line)
    return lines


def choose_format(video_id: str, formats: list[dict], downloads_dir: Path = ds.DOWNLOADS_DIR,
                  ask: Callable[[str], str] = input, show: Callable[[str], None] = print,
                  color: bool | None = None) -> str:
    """Show the formats and return the id of the one picked: a list number, a format id, or Enter for the default."""
    if not formats:
        raise ds.DatasetError(f"{video_id} offers no video formats")
    color = sys.stdout.isatty() if color is None else color
    downloaded = downloaded_ids(video_id, formats, downloads_dir)
    default = default_format(formats, downloaded)
    show(f"Formats of {video_id}:")
    for line in render(formats, downloaded, default, color):
        show(line)
    by_id = {f["format_id"]: f["format_id"] for f in formats}
    while True:
        answer = ask(f"Format [Enter = {default}]: ").strip()
        if not answer:
            return default
        if answer in by_id:
            return answer
        if answer.isdigit() and 1 <= int(answer) <= len(formats):
            return formats[int(answer) - 1]["format_id"]
        show(f"Not a format: {answer!r}. Give a list number or a format id.")


# --- Arrow-key menu --------------------------------------------------------------------------------

_REVERSE = "\033[7m"
_ESCAPES = {"[A": "up", "[B": "down", "[5~": "pageup", "[6~": "pagedown", "[H": "home", "[F": "end",
            "[1~": "home", "[4~": "end", "OA": "up", "OB": "down", "OH": "home", "OF": "end"}
_PLAIN = {"\r": "enter", "\n": "enter", "k": "up", "j": "down", "q": "cancel", "\x03": "cancel"}


def read_key(fd: int, wait: float = 0.05) -> str:
    """The next key from a terminal in cbreak mode: up, down, pageup, pagedown, home, end, enter, cancel, or ''."""
    import os
    import select

    char = os.read(fd, 1).decode(errors="ignore")
    if char != "\x1b":
        return _PLAIN.get(char, "")
    sequence = ""
    while len(sequence) < 3 and select.select([fd], [], [], wait)[0]:
        sequence += os.read(fd, 1).decode(errors="ignore")
        if sequence in _ESCAPES:
            return _ESCAPES[sequence]
    return "cancel" if not sequence else ""  # a lone Escape cancels; an unknown sequence is ignored


def menu(formats: list[dict], downloaded: set[str], default: str, keys: Callable[[], str],
         write: Callable[[str], None], height: int, color: bool = True) -> str | None:
    """Pick a format with the arrow keys; returns its id, or None if cancelled.

    `keys()` yields the next key name (see `read_key`). The list scrolls inside `height` lines.
    """
    ids = [f["format_id"] for f in formats]
    cursor = ids.index(default)
    top = 0
    height = max(1, min(height, len(formats)))
    lines = render(formats, downloaded, default, color)
    drawn = 0
    while True:
        top = min(max(top, cursor - height + 1), cursor) if cursor < top or cursor >= top + height else top
        view = [(_REVERSE + line if i == cursor else line) for i, line in enumerate(lines)][top:top + height]
        view.append(f"{_DIM if color else ''}↑/↓ choose · PgUp/PgDn · Enter select · q cancel   "
                    f"({cursor + 1}/{len(formats)}){_RESET if color else ''}")
        write((f"\033[{drawn}F" if drawn else "") + "".join(f"\033[2K{line}\n" for line in view))
        drawn = len(view)
        key = keys()
        if key == "enter":
            return ids[cursor]
        if key == "cancel":
            return None
        step = {"up": -1, "down": 1, "pageup": -height, "pagedown": height}.get(key)
        if step is not None:
            cursor = min(max(cursor + step, 0), len(formats) - 1)
        elif key == "home":
            cursor = 0
        elif key == "end":
            cursor = len(formats) - 1


def choose_with_arrows(video_id: str, formats: list[dict], downloads_dir: Path = ds.DOWNLOADS_DIR) -> str:
    """Like `choose_format`, but pick with the up/down arrow keys (typed answers when stdin isn't a terminal)."""
    if not formats:
        raise ds.DatasetError(f"{video_id} offers no video formats")
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return choose_format(video_id, formats, downloads_dir)
    import shutil
    import termios
    import tty

    downloaded = downloaded_ids(video_id, formats, downloads_dir)
    default = default_format(formats, downloaded)
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    height = max(5, shutil.get_terminal_size().lines - 4)
    print(f"Formats of {video_id}:")
    sys.stdout.write("\033[?25l")  # hide the cursor while choosing
    try:
        tty.setcbreak(fd)
        chosen = menu(formats, downloaded, default, lambda: read_key(fd),
                      lambda text: (sys.stdout.write(text), sys.stdout.flush()), height)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
    if chosen is None:
        raise ds.DatasetError("format choice cancelled")
    print(f"Using format {chosen}")
    return chosen

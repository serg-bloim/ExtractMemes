import pytest

from extract_memes.timecode_sender import TimecodeSender


class Recorder(TimecodeSender):
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def send(self, timecodes: list[str], source: str) -> None:
        self.calls.append((list(timecodes), source))


def test_timecode_sender_is_abstract():
    with pytest.raises(TypeError):
        TimecodeSender()


def test_recorder_records_the_call():
    recorder = Recorder()
    timecodes = ["0:07 Мем 1", "0:28 Мем 2"]

    recorder.send(timecodes, "https://youtu.be/xyz")

    assert recorder.calls == [(timecodes, "https://youtu.be/xyz")]

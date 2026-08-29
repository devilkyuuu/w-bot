import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from wbot.domain import SourceKind, SupportedUrl
from wbot.extractors import video


def test_portrait_1080p_format_is_allowed(monkeypatch: Any) -> None:
    class FakeYoutubeDL:
        def __init__(self, options: dict[str, Any]) -> None:
            assert "[height<=1920][width<=1920]" in options["format"]
            assert options["format"].endswith("/best[ext=mp4]")

        def __enter__(self) -> "FakeYoutubeDL":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def extract_info(self, url: str, *, download: bool) -> dict[str, Any]:
            return {"width": 1080, "height": 1920}

    monkeypatch.setattr(video, "YoutubeDL", FakeYoutubeDL)
    extractor = video.VideoExtractor(max_seconds=300, max_bytes=700_000_000)
    url = SupportedUrl(
        "https://www.facebook.com/reel/1",
        "https://www.facebook.com/reel/1",
        SourceKind.FACEBOOK,
    )

    metadata = extractor._extract_info(url.normalized, False, Path("."))

    assert metadata["width"] == 1080
    assert metadata["height"] == 1920


@pytest.mark.parametrize(
    ("codec", "width", "height", "scaled"),
    (("av1", 1080, 1920, False), ("h264", 2160, 3840, True)),
)
def test_incompatible_video_is_transcoded(
    monkeypatch: Any,
    tmp_path: Path,
    codec: str,
    width: int,
    height: int,
    scaled: bool,
) -> None:
    source = tmp_path / "media.mp4"
    source.write_bytes(b"source")
    probes = iter(((codec, width, height), ("h264", 1080, 1920)))
    ffmpeg_commands: list[list[str]] = []

    def run(command: list[str] | tuple[str, ...], **kwargs: Any) -> Any:
        if command[0] == "ffprobe":
            codec_name, probed_width, probed_height = next(probes)
            return SimpleNamespace(
                stdout=json.dumps(
                    {
                        "streams": [
                            {
                                "codec_name": codec_name,
                                "width": probed_width,
                                "height": probed_height,
                            }
                        ]
                    }
                )
            )
        ffmpeg_commands.append(list(command))
        Path(command[-1]).write_bytes(b"compatible")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)

    output, stream = video.VideoExtractor(
        max_seconds=300, max_bytes=700_000_000
    )._ensure_compatible(source)

    assert output.name == "compatible.mp4"
    assert stream == video.VideoStream("h264", 1080, 1920)
    assert ("-vf" in ffmpeg_commands[0]) is scaled
    assert not source.exists()

"""Video probing and frame iteration with exact presentation timestamps."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import av
import numpy as np


class VideoError(RuntimeError):
    """Raised when a video cannot be parsed or decoded consistently."""


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    width: int
    height: int
    fps: float
    frame_count: int
    duration_s: float
    codec: str
    time_base: str


@dataclass(frozen=True)
class Frame:
    index: int
    pts_s: float
    rgb: np.ndarray
    width: int
    height: int


def probe(path: Path) -> VideoInfo:
    """Read container metadata without decoding frames."""
    if not path.is_file():
        raise VideoError(f"video does not exist: {path}")
    with av.open(str(path)) as container:
        stream = _video_stream(container)
        fps = _fps(stream)
        duration_s = _duration_s(stream, container)
        frame_count = int(stream.frames or 0)
        if frame_count <= 0 and fps > 0 and duration_s > 0:
            frame_count = int(round(fps * duration_s))
        return VideoInfo(
            path=path,
            width=int(stream.width),
            height=int(stream.height),
            fps=fps,
            frame_count=frame_count,
            duration_s=duration_s,
            codec=stream.codec_context.name,
            time_base=str(stream.time_base),
        )


def iter_frames(
    path: Path,
    *,
    start_s: float | None = None,
    end_s: float | None = None,
    stride: int = 1,
    limit: int | None = None,
) -> Iterator[Frame]:
    """Yield decoded frames in order, with PTS from the container.

    Decoding walks the whole stream and filters by PTS. That is intentional:
    seeking can land on a keyframe before the requested time, and frame index
    is not a reliable time base for VFR clips.
    """
    if stride < 1:
        raise VideoError("stride must be >= 1")
    with av.open(str(path)) as container:
        stream = _video_stream(container)
        time_base = stream.time_base
        if time_base is None:
            raise VideoError(f"video stream has no time base: {path}")

        selected = 0
        for index, frame in enumerate(container.decode(stream)):
            if frame.pts is None:
                raise VideoError(f"frame {index} has no PTS: {path}")
            pts_s = float(frame.pts * time_base)
            if start_s is not None and pts_s < start_s - 1e-9:
                continue
            if end_s is not None and pts_s > end_s + 1e-9:
                break
            if selected % stride != 0:
                selected += 1
                continue

            rgb = frame.to_ndarray(format="rgb24")
            yield Frame(
                index=index,
                pts_s=pts_s,
                rgb=np.ascontiguousarray(rgb),
                width=int(frame.width),
                height=int(frame.height),
            )
            selected += 1
            if limit is not None and selected >= limit:
                break


def _video_stream(container: av.container.InputContainer) -> av.video.stream.VideoStream:
    if not container.streams.video:
        raise VideoError("container has no video stream")
    return container.streams.video[0]


def _fps(stream: av.video.stream.VideoStream) -> float:
    rate = stream.average_rate or stream.guessed_rate
    if rate is None or float(rate) <= 0:
        raise VideoError("video stream has no usable frame rate")
    return float(rate)


def _duration_s(
    stream: av.video.stream.VideoStream,
    container: av.container.InputContainer,
) -> float:
    if stream.duration is not None and stream.time_base is not None:
        return float(stream.duration * stream.time_base)
    if container.duration is not None:
        return float(container.duration / 1_000_000)
    return 0.0

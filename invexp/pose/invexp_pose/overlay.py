"""Render pose landmarks and gait events over the source video."""

from __future__ import annotations

import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from .constants import LANDMARK_NAMES, SIDE_LANDMARKS
from .landmarks import WideLandmarks, load_landmarks
from .video import Frame, iter_frames, probe

SIDE_COLORS: dict[str, tuple[int, int, int]] = {
    "left": (0, 220, 255),
    "right": (255, 150, 40),
}
NEUTRAL_COLOR = (220, 220, 220)
CONTACT_COLOR = (255, 235, 0)
TOE_OFF_COLOR = (180, 255, 140)

# Body and foot connections only. Face and hand points are still drawn as dots,
# but their connections add clutter without helping gait inspection.
BODY_CONNECTIONS: tuple[tuple[str, str], ...] = (
    ("left_shoulder", "right_shoulder"),
    ("left_shoulder", "left_elbow"),
    ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"),
    ("right_elbow", "right_wrist"),
    ("left_shoulder", "left_hip"),
    ("right_shoulder", "right_hip"),
    ("left_hip", "right_hip"),
    ("left_hip", "left_knee"),
    ("left_knee", "left_ankle"),
    ("right_hip", "right_knee"),
    ("right_knee", "right_ankle"),
    ("left_ankle", "left_heel"),
    ("left_heel", "left_foot_index"),
    ("left_ankle", "left_foot_index"),
    ("right_ankle", "right_heel"),
    ("right_heel", "right_foot_index"),
    ("right_ankle", "right_foot_index"),
)

GAIT_JOINTS = {
    name
    for landmarks in SIDE_LANDMARKS.values()
    for name in landmarks.values()
}


class OverlayError(RuntimeError):
    """Raised when an overlay cannot be rendered."""


@dataclass(frozen=True)
class OverlayResult:
    video_id: str
    output: Path
    frames_encoded: int
    start_s: float
    end_s: float
    width: int
    height: int
    fps: float
    elapsed_s: float
    bytes_written: int


def render_overlay(
    video_path: Path,
    landmarks_path: Path,
    output_path: Path,
    *,
    video_id: str,
    events_path: Path | None = None,
    start_s: float | None = None,
    end_s: float | None = None,
    full: bool = False,
    padding_s: float = 1.0,
    max_width: int = 1280,
    visibility_threshold: float = 0.5,
    crf: int = 22,
) -> OverlayResult:
    """Draw MediaPipe landmarks and contact/toe-off events on a video.

    The default window is the detected pose range plus ``padding_s``. That
    keeps the exported clip short without hiding the walk before or after the
    annotated segment. Pass ``full=True`` to render the whole source clip.
    """
    if not video_path.is_file():
        raise OverlayError(f"video does not exist: {video_path}")
    if max_width < 32:
        raise OverlayError("max_width must be >= 32")

    wide = load_landmarks(landmarks_path)
    events = _load_events(events_path)
    info = probe(video_path)
    out_width, out_height = _output_size(info.width, info.height, max_width)
    window_start, window_end = _window(
        wide,
        start_s=start_s,
        end_s=end_s,
        full=full,
        padding_s=padding_s,
        duration_s=info.duration_s,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    frames_encoded = 0
    out_index = 0
    font = _font(max(16, out_width // 55))

    container = av.open(str(output_path), mode="w")
    stream = _add_stream(container, info.fps, out_width, out_height, crf=crf)
    try:
        for frame in iter_frames(
            video_path,
            start_s=window_start,
            end_s=window_end,
        ):
            image = Image.fromarray(frame.rgb).resize(
                (out_width, out_height),
                Image.Resampling.LANCZOS,
            )
            _draw_frame(
                image,
                frame=frame,
                wide=wide,
                events=events,
                video_id=video_id,
                out_width=out_width,
                out_height=out_height,
                visibility_threshold=visibility_threshold,
                font=font,
            )
            video_frame = av.VideoFrame.from_ndarray(
                np.ascontiguousarray(np.asarray(image)),
                format="rgb24",
            )
            video_frame.pts = out_index
            for packet in stream.encode(video_frame):
                container.mux(packet)
            frames_encoded += 1
            out_index += 1

        for packet in stream.encode():
            container.mux(packet)
    finally:
        container.close()

    if frames_encoded == 0:
        output_path.unlink(missing_ok=True)
        raise OverlayError(
            f"no frames encoded for window {window_start:.3f}-{window_end:.3f} s"
        )

    return OverlayResult(
        video_id=video_id,
        output=output_path,
        frames_encoded=frames_encoded,
        start_s=window_start,
        end_s=window_end,
        width=out_width,
        height=out_height,
        fps=info.fps,
        elapsed_s=round(time.monotonic() - started, 3),
        bytes_written=output_path.stat().st_size,
    )


def _add_stream(
    container: av.container.OutputContainer,
    fps: float,
    width: int,
    height: int,
    *,
    crf: int,
) -> av.video.stream.VideoStream:
    rate = _fraction(fps)
    try:
        stream = container.add_stream("libx264", rate=rate)
        stream.options = {"crf": str(crf), "preset": "veryfast"}
    except (av.error.FFmpegError, ValueError):
        stream = container.add_stream("mpeg4", rate=rate)
        stream.options = {"qscale": "4"}
    stream.width = width
    stream.height = height
    stream.pix_fmt = "yuv420p"
    stream.thread_type = "AUTO"
    return stream


def _fraction(value: float) -> Fraction:
    return Fraction(round(value * 1000), 1000)


def _output_size(width: int, height: int, max_width: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise OverlayError("video has invalid dimensions")
    out_width = min(width, max_width)
    out_width -= out_width % 2
    out_height = int(round(height * out_width / width))
    out_height -= out_height % 2
    if out_width < 2 or out_height < 2:
        raise OverlayError("video is too small to render")
    return out_width, out_height


def _window(
    wide: WideLandmarks,
    *,
    start_s: float | None,
    end_s: float | None,
    full: bool,
    padding_s: float,
    duration_s: float,
) -> tuple[float | None, float | None]:
    if full:
        return start_s, end_s
    if start_s is not None and end_s is not None:
        if end_s <= start_s:
            raise OverlayError("end must be greater than start")
        return start_s, end_s

    detected = _detected_mask(wide)
    if not detected.any():
        raise OverlayError("landmark table contains no detected frames")
    pts = wide.values.index.get_level_values("pts_s").to_numpy(dtype=float)
    first, last = _longest_detected_run(pts[detected])
    window_start = max(0.0, first - padding_s) if start_s is None else start_s
    window_end = last + padding_s if end_s is None else end_s
    if duration_s > 0:
        window_end = min(window_end, duration_s)
    if window_end <= window_start:
        raise OverlayError("detected window is empty")
    return window_start, window_end


def _longest_detected_run(
    pts_s: np.ndarray,
    *,
    max_gap_s: float = 0.5,
) -> tuple[float, float]:
    """Return the longest contiguous detection span.

    Short false positives before or after the walk would otherwise stretch the
    default overlay to almost the whole clip. Gaps longer than ``max_gap_s``
    split runs; the longest one is the actual subject pass.
    """
    times = np.sort(pts_s[np.isfinite(pts_s)])
    if len(times) == 0:
        raise OverlayError("no finite detection timestamps")
    cuts = np.flatnonzero(np.diff(times) > max_gap_s)
    starts = np.r_[0, cuts + 1]
    ends = np.r_[cuts, len(times) - 1]
    lengths = times[ends] - times[starts]
    best = int(np.argmax(lengths))
    return float(times[starts[best]]), float(times[ends[best]])


def _detected_mask(wide: WideLandmarks) -> np.ndarray:
    names = [name for name in LANDMARK_NAMES if ("x", name) in wide.values.columns]
    if not names:
        return np.zeros(len(wide.values), dtype=bool)
    values = np.column_stack([wide.field("x", name) for name in names])
    return np.isfinite(values).any(axis=1)


def _load_events(events_path: Path | None) -> pd.DataFrame:
    if events_path is None:
        return pd.DataFrame()
    if not events_path.is_file():
        raise OverlayError(f"events file does not exist: {events_path}")
    return pd.read_csv(events_path, dtype={"video_id": str})


def _draw_frame(
    image: Image.Image,
    *,
    frame: Frame,
    wide: WideLandmarks,
    events: pd.DataFrame,
    video_id: str,
    out_width: int,
    out_height: int,
    visibility_threshold: float,
    font: ImageFont.ImageFont,
) -> None:
    row = _row_for_frame(wide, frame.index)
    if row is None:
        _draw_hud(
            image,
            video_id=video_id,
            frame=frame,
            detected=False,
            event_labels=[],
            font=font,
        )
        return

    points: dict[str, tuple[float, float]] = {}
    visibilities: dict[str, float] = {}
    for name in LANDMARK_NAMES:
        if ("x", name) not in wide.values.columns:
            continue
        x = float(wide.values[("x", name)].iloc[row])
        y = float(wide.values[("y", name)].iloc[row])
        visibility = float(wide.values[("visibility", name)].iloc[row])
        if not (np.isfinite(x) and np.isfinite(y)):
            continue
        points[name] = (x * out_width, y * out_height)
        visibilities[name] = visibility

    detected = bool(points)
    if detected:
        _draw_landmarks(
            image,
            points=points,
            visibilities=visibilities,
            threshold=visibility_threshold,
            out_width=out_width,
        )
        event_labels = _draw_events(
            image,
            frame=frame,
            events=events,
            points=points,
            visibilities=visibilities,
            threshold=visibility_threshold,
            font=font,
        )
    else:
        event_labels = []

    _draw_hud(
        image,
        video_id=video_id,
        frame=frame,
        detected=detected,
        event_labels=event_labels,
        font=font,
    )


def _row_for_frame(wide: WideLandmarks, frame_index: int) -> int | None:
    frames = wide.values.index.get_level_values("frame")
    matches = np.flatnonzero(frames == frame_index)
    if len(matches) == 0:
        return None
    return int(matches[0])


def _draw_landmarks(
    image: Image.Image,
    *,
    points: dict[str, tuple[float, float]],
    visibilities: dict[str, float],
    threshold: float,
    out_width: int,
) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    line_width = max(2, out_width // 640)
    point_radius = max(2.0, out_width / 640)

    for start_name, end_name in BODY_CONNECTIONS:
        if start_name not in points or end_name not in points:
            continue
        if visibilities[start_name] < threshold or visibilities[end_name] < threshold:
            continue
        color = SIDE_COLORS[_side_for(start_name)]
        draw.line(
            [points[start_name], points[end_name]],
            fill=(*color, 210),
            width=line_width,
        )

    for name, (x, y) in points.items():
        visibility = visibilities[name]
        if visibility < threshold:
            continue
        color = SIDE_COLORS[_side_for(name)]
        radius = point_radius * (1.8 if name in GAIT_JOINTS else 1.0)
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=(*color, 235),
            outline=(0, 0, 0, 180),
            width=1,
        )


def _draw_events(
    image: Image.Image,
    *,
    frame: Frame,
    events: pd.DataFrame,
    points: dict[str, tuple[float, float]],
    visibilities: dict[str, float],
    threshold: float,
    font: ImageFont.ImageFont,
) -> list[tuple[str, tuple[int, int, int]]]:
    if events.empty:
        return []
    draw = ImageDraw.Draw(image, "RGBA")
    labels: list[tuple[str, tuple[int, int, int]]] = []
    for _, event in events.iterrows():
        side = str(event.get("side", ""))
        if side not in SIDE_COLORS:
            continue
        for kind, frame_column, color in (
            ("contact", "contact_frame", CONTACT_COLOR),
            ("toe-off", "toe_off_frame", TOE_OFF_COLOR),
        ):
            value = event.get(frame_column)
            if pd.isna(value) or int(value) != frame.index:
                continue
            point = _event_point(points, visibilities, side, threshold)
            if point is None:
                labels.append((f"{side[0].upper()} {kind}", color))
                continue
            x, y = point
            radius = 22
            draw.ellipse(
                (x - radius, y - radius, x + radius, y + radius),
                outline=(*color, 255),
                width=3,
            )
            draw.line(
                [(x - radius - 8, y), (x + radius + 8, y)],
                fill=(*color, 180),
                width=1,
            )
            draw.line(
                [(x, y - radius - 8), (x, y + radius + 8)],
                fill=(*color, 180),
                width=1,
            )
            label = f"{side[0].upper()} {kind}"
            draw.text(
                (x + radius + 6, y - radius - 6),
                label,
                font=font,
                fill=(*color, 255),
                stroke_width=2,
                stroke_fill=(0, 0, 0),
            )
            labels.append((label, color))
    return labels


def _event_point(
    points: dict[str, tuple[float, float]],
    visibilities: dict[str, float],
    side: str,
    threshold: float,
) -> tuple[float, float] | None:
    for joint in ("ankle", "heel", "foot_index"):
        name = SIDE_LANDMARKS[side][joint]
        if name in points and visibilities.get(name, 0.0) >= threshold:
            return points[name]
    return None


def _draw_hud(
    image: Image.Image,
    *,
    video_id: str,
    frame: Frame,
    detected: bool,
    event_labels: list[tuple[str, tuple[int, int, int]]],
    font: ImageFont.ImageFont,
) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    lines = [
        f"{video_id}   frame {frame.index}   t={frame.pts_s:.3f} s",
        "pose: detected" if detected else "pose: no detection",
    ]
    lines.extend(label for label, _ in event_labels)
    line_height = max(18, getattr(font, "size", 16) + 6)
    box_width = max(
        _text_width(draw, line, font) for line in lines
    ) + 24
    box_height = line_height * len(lines) + 16
    draw.rectangle((12, 12, 12 + box_width, 12 + box_height), fill=(0, 0, 0, 170))
    for index, line in enumerate(lines):
        color = (255, 255, 255)
        if index >= 2:
            color = event_labels[index - 2][1]
        draw.text(
            (24, 20 + index * line_height),
            line,
            font=font,
            fill=(*color, 255),
        )


def _text_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return int(box[2] - box[0])


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _side_for(name: str) -> str:
    if name.startswith("left_"):
        return "left"
    if name.startswith("right_"):
        return "right"
    return "left"

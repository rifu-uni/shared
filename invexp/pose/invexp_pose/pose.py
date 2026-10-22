"""MediaPipe Pose Landmarker inference and long-table export."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import time
import urllib.request
from dataclasses import asdict
from pathlib import Path

import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

from .config import Config
from .constants import LANDMARK_COLUMNS, LANDMARK_NAMES
from .video import VideoInfo, iter_frames, probe

MODEL_URLS: dict[str, str] = {
    "lite": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
    "full": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_full/float16/1/pose_landmarker_full.task",
    "heavy": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task",
}

MODEL_SHA256: dict[str, str] = {
    "lite": "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a",
    "full": "5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1",
    "heavy": "64437af838a65d18e5ba7a0d39b465540069bc8aae8308de3e318aad31fcbc7b",
}


class PoseError(RuntimeError):
    """Raised when the model or inference output violates the contract."""


def ensure_model(config: Config) -> Path:
    path = config.model_path
    if path.is_file():
        _verify_hash(path, MODEL_SHA256[config.model])
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    url = MODEL_URLS[config.model]
    with urllib.request.urlopen(url) as response, path.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    _verify_hash(path, MODEL_SHA256[config.model])
    return path


def extract_video(
    video_path: Path,
    output_path: Path,
    *,
    video_id: str,
    config: Config,
    start_s: float | None = None,
    end_s: float | None = None,
    stride: int = 1,
    limit: int | None = None,
) -> dict[str, object]:
    """Run pose inference over one video and write a gzipped long table."""
    info = probe(video_path)
    model_path = ensure_model(config)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    frames_processed = 0
    frames_detected = 0
    timestamp_adjustments = 0
    last_timestamp_ms = -1
    first_pts_s: float | None = None
    last_pts_s: float | None = None

    options = vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=config.min_pose_detection_confidence,
        min_pose_presence_confidence=config.min_pose_presence_confidence,
        min_tracking_confidence=config.min_tracking_confidence,
    )
    landmarker = vision.PoseLandmarker.create_from_options(options)

    try:
        with gzip.open(output_path, "wt", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(LANDMARK_COLUMNS)
            for frame in iter_frames(
                video_path,
                start_s=start_s,
                end_s=end_s,
                stride=stride,
                limit=limit,
            ):
                image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=np.ascontiguousarray(frame.rgb),
                )
                timestamp_ms = int(round(frame.pts_s * 1000))
                if timestamp_ms <= last_timestamp_ms:
                    timestamp_ms = last_timestamp_ms + 1
                    timestamp_adjustments += 1
                last_timestamp_ms = timestamp_ms

                result = landmarker.detect_for_video(image, timestamp_ms)
                detected = bool(result.pose_landmarks)
                if detected and len(result.pose_landmarks[0]) != len(LANDMARK_NAMES):
                    raise PoseError(
                        f"expected {len(LANDMARK_NAMES)} landmarks, "
                        f"got {len(result.pose_landmarks[0])}"
                    )
                frames_processed += 1
                frames_detected += int(detected)
                first_pts_s = frame.pts_s if first_pts_s is None else first_pts_s
                last_pts_s = frame.pts_s
                _write_frame_rows(
                    writer,
                    video_id=video_id,
                    frame_index=frame.index,
                    pts_s=frame.pts_s,
                    width_px=frame.width,
                    height_px=frame.height,
                    result=result,
                )
    finally:
        landmarker.close()

    if info.frame_count and start_s is None and end_s is None and stride == 1 and limit is None:
        if frames_processed != info.frame_count:
            raise PoseError(
                f"decoded {frames_processed} frames, container reports {info.frame_count}"
            )

    metadata: dict[str, object] = {
        "video_id": video_id,
        "video": asdict(info),
        "frames_processed": frames_processed,
        "frames_detected": frames_detected,
        "detection_rate": frames_detected / frames_processed if frames_processed else 0.0,
        "first_pts_s": first_pts_s,
        "last_pts_s": last_pts_s,
        "timestamp_adjustments": timestamp_adjustments,
        "model": config.model,
        "model_sha256": MODEL_SHA256[config.model],
        "start_s": start_s,
        "end_s": end_s,
        "stride": stride,
        "limit": limit,
        "elapsed_s": round(time.monotonic() - started, 3),
    }
    metadata["video"]["path"] = str(video_path)
    metadata_path = output_path.with_suffix("").with_suffix(".json")
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def _write_frame_rows(
    writer: csv.writer,
    *,
    video_id: str,
    frame_index: int,
    pts_s: float,
    width_px: int,
    height_px: int,
    result: vision.PoseLandmarkerResult,
) -> None:
    pose = result.pose_landmarks[0] if result.pose_landmarks else []
    world = result.pose_world_landmarks[0] if result.pose_world_landmarks else []
    detected = bool(pose)
    nan = math.nan

    for landmark_id, name in enumerate(LANDMARK_NAMES):
        landmark = pose[landmark_id] if detected else None
        world_landmark = world[landmark_id] if detected and world else None
        writer.writerow(
            (
                video_id,
                frame_index,
                f"{pts_s:.9f}",
                width_px,
                height_px,
                landmark_id,
                name,
                _value(landmark, "x", nan),
                _value(landmark, "y", nan),
                _value(landmark, "z", nan),
                _value(landmark, "visibility", nan),
                _value(landmark, "presence", nan),
                _value(world_landmark, "x", nan),
                _value(world_landmark, "y", nan),
                _value(world_landmark, "z", nan),
                int(detected),
            )
        )


def _value(landmark: object | None, field: str, default: float) -> float:
    if landmark is None:
        return default
    value = getattr(landmark, field, default)
    return float(value)


def _verify_hash(path: Path, expected: str) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        raise PoseError(
            f"model hash mismatch for {path.name}: expected {expected}, got {digest}"
        )

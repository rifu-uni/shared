"""Sagittal joint angles from MediaPipe landmarks.

All angles are image-plane angles. They are valid for a tripod, near-sagittal
view; they are not 3D joint angles. Coordinates stay in pixels so the output
does not pretend to have a metric scale that the recordings do not provide.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike
from scipy.signal import savgol_filter

from .config import Config
from .constants import ALL_SIDES, SIDE_LANDMARKS
from .landmarks import LandmarkError, WideLandmarks

KINEMATIC_COLUMNS: tuple[str, ...] = (
    "video_id",
    "frame",
    "pts_s",
    "side",
    "hip_flexion_deg",
    "knee_flexion_deg",
    "ankle_angle_deg",
    "foot_pitch_deg",
    "trunk_inclination_deg",
    "shoulder_x_px",
    "shoulder_y_px",
    "hip_x_px",
    "hip_y_px",
    "knee_x_px",
    "knee_y_px",
    "ankle_x_px",
    "ankle_y_px",
    "heel_x_px",
    "heel_y_px",
    "foot_index_x_px",
    "foot_index_y_px",
    "confidence",
    "valid",
)


def compute_kinematics(
    wide: WideLandmarks,
    *,
    video_id: str,
    config: Config,
    sides: tuple[str, ...] = ALL_SIDES,
) -> pd.DataFrame:
    frame = wide.values.index.get_level_values("frame").to_numpy()
    pts_s = wide.values.index.get_level_values("pts_s").to_numpy(dtype=float)
    records: list[pd.DataFrame] = []

    for side in sides:
        if side not in SIDE_LANDMARKS:
            raise LandmarkError(f"unknown side: {side}")
        records.append(_side_kinematics(wide, frame, pts_s, video_id, side, config))

    return pd.concat(records, ignore_index=True)[list(KINEMATIC_COLUMNS)]


def _side_kinematics(
    wide: WideLandmarks,
    frame: np.ndarray,
    pts_s: np.ndarray,
    video_id: str,
    side: str,
    config: Config,
) -> pd.DataFrame:
    points = _smoothed_points(wide, side, config)
    shoulder = points["shoulder"]
    hip = points["hip"]
    knee = points["knee"]
    ankle = points["ankle"]
    heel = points["heel"]
    foot_index = points["foot_index"]

    hip_flexion = 180.0 - _angle_deg(shoulder, hip, knee)
    knee_flexion = 180.0 - _angle_deg(hip, knee, ankle)
    ankle_angle = _angle_deg(knee, ankle, foot_index)
    foot_pitch = _foot_pitch_deg(heel, foot_index)
    trunk_inclination = _trunk_inclination_deg(shoulder, hip)

    confidence = np.minimum.reduce(
        [hip.visibility, knee.visibility, ankle.visibility]
    )
    valid = hip.visible & knee.visible & ankle.visible
    valid &= np.isfinite(knee_flexion)

    return pd.DataFrame(
        {
            "video_id": video_id,
            "frame": frame,
            "pts_s": pts_s,
            "side": side,
            "hip_flexion_deg": hip_flexion,
            "knee_flexion_deg": knee_flexion,
            "ankle_angle_deg": ankle_angle,
            "foot_pitch_deg": foot_pitch,
            "trunk_inclination_deg": trunk_inclination,
            "shoulder_x_px": shoulder.x_raw,
            "shoulder_y_px": shoulder.y_raw,
            "hip_x_px": hip.x_raw,
            "hip_y_px": hip.y_raw,
            "knee_x_px": knee.x_raw,
            "knee_y_px": knee.y_raw,
            "ankle_x_px": ankle.x_raw,
            "ankle_y_px": ankle.y_raw,
            "heel_x_px": heel.x_raw,
            "heel_y_px": heel.y_raw,
            "foot_index_x_px": foot_index.x_raw,
            "foot_index_y_px": foot_index.y_raw,
            "confidence": confidence,
            "valid": valid,
        }
    )


class _Point:
    def __init__(
        self,
        x_raw: np.ndarray,
        y_raw: np.ndarray,
        x_smooth: np.ndarray,
        y_smooth: np.ndarray,
        visibility: np.ndarray,
        visible: np.ndarray,
    ) -> None:
        self.x_raw = x_raw
        self.y_raw = y_raw
        self.x = x_smooth
        self.y = y_smooth
        self.visibility = visibility
        self.visible = visible


def _smoothed_points(
    wide: WideLandmarks,
    side: str,
    config: Config,
) -> dict[str, _Point]:
    points: dict[str, _Point] = {}
    for role, name in SIDE_LANDMARKS[side].items():
        visibility = wide.field("visibility", name)
        visible = np.isfinite(visibility) & (visibility >= config.visibility_threshold)
        x_raw = wide.field("x", name) * wide.width_px
        y_raw = wide.field("y", name) * wide.height_px
        x_smooth = _smooth_within_segments(x_raw, visible, config)
        y_smooth = _smooth_within_segments(y_raw, visible, config)
        points[role] = _Point(
            x_raw=x_raw,
            y_raw=y_raw,
            x_smooth=x_smooth,
            y_smooth=y_smooth,
            visibility=visibility,
            visible=visible,
        )
    return points


def _smooth_within_segments(
    values: np.ndarray,
    valid: np.ndarray,
    config: Config,
) -> np.ndarray:
    """Savitzky-Golay inside contiguous valid runs only.

    No interpolation across gaps: a missing ankle must stay missing, otherwise
    the angle series invents a leg during occlusion.
    """
    result = values.astype(float, copy=True)
    for start, stop in _runs(valid):
        if stop - start < config.smoothing_window:
            continue
        result[start:stop] = savgol_filter(
            result[start:stop],
            window_length=config.smoothing_window,
            polyorder=config.smoothing_order,
            mode="interp",
        )
    return result


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(mask):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(mask)))
    return runs


def _angle_deg(a: _Point, b: _Point, c: _Point) -> np.ndarray:
    """Angle at b between ba and bc, in degrees."""
    ba_x = a.x - b.x
    ba_y = a.y - b.y
    bc_x = c.x - b.x
    bc_y = c.y - b.y
    dot = ba_x * bc_x + ba_y * bc_y
    norm = np.hypot(ba_x, ba_y) * np.hypot(bc_x, bc_y)
    cosine = np.divide(dot, norm, out=np.full_like(dot, np.nan), where=norm > 0)
    return np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0)))


def _foot_pitch_deg(heel: _Point, foot_index: _Point) -> np.ndarray:
    """Image-plane foot angle, positive when the toe is above the heel."""
    return np.degrees(np.arctan2(-(foot_index.y - heel.y), foot_index.x - heel.x))


def _trunk_inclination_deg(shoulder: _Point, hip: _Point) -> np.ndarray:
    """Forward lean from vertical, positive toward image +x."""
    return np.degrees(np.arctan2(shoulder.x - hip.x, hip.y - shoulder.y))


def angle_deg_from_arrays(
    ax: ArrayLike,
    ay: ArrayLike,
    bx: ArrayLike,
    by: ArrayLike,
    cx: ArrayLike,
    cy: ArrayLike,
) -> np.ndarray:
    """Public helper used by tests and by future custom landmark sources."""
    ax, ay, bx, by, cx, cy = np.broadcast_arrays(
        *[np.asarray(value, dtype=float) for value in (ax, ay, bx, by, cx, cy)]
    )
    ba_x = ax - bx
    ba_y = ay - by
    bc_x = cx - bx
    bc_y = cy - by
    dot = ba_x * bc_x + ba_y * bc_y
    norm = np.hypot(ba_x, ba_y) * np.hypot(bc_x, bc_y)
    cosine = np.divide(dot, norm, out=np.full_like(dot, np.nan), where=norm > 0)
    return np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0)))

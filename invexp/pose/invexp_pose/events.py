"""Contact and toe-off detection from foot trajectories.

The primary signal is the foot's forward offset relative to the hip. During
swing the foot moves forward; at contact it reaches its forward-most point and
then travels backward relative to the hip through stance. That reversal is much
less ambiguous than a vertical minimum, because the foot can stay near the
ground for several frames around heel strike.

A vertical-foot fallback is kept for clips where the hip landmark is missing.
The detector is a timing proxy, not a force measurement: IMU and FSR remain the
impact references.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from .config import Config
from .constants import ALL_SIDES, SIDE_LANDMARKS
from .kinematics import _smooth_within_segments
from .landmarks import LandmarkError, WideLandmarks

EVENT_COLUMNS: tuple[str, ...] = (
    "video_id",
    "side",
    "event_index",
    "contact_frame",
    "contact_pts_s",
    "contact_y_px",
    "toe_off_frame",
    "toe_off_pts_s",
    "stance_s",
    "stride_s",
    "cadence_spm",
    "prominence_px",
    "confidence",
)


def detect_events(
    wide: WideLandmarks,
    *,
    video_id: str,
    config: Config,
    sides: tuple[str, ...] = ALL_SIDES,
) -> pd.DataFrame:
    frames = wide.values.index.get_level_values("frame").to_numpy()
    pts_s = wide.values.index.get_level_values("pts_s").to_numpy(dtype=float)
    records: list[pd.DataFrame] = []

    for side in sides:
        if side not in SIDE_LANDMARKS:
            raise LandmarkError(f"unknown side: {side}")
        records.append(_side_events(wide, frames, pts_s, video_id, side, config))

    result = pd.concat(records, ignore_index=True)
    if result.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    return result.sort_values(["side", "contact_pts_s"]).reset_index(drop=True)[
        list(EVENT_COLUMNS)
    ]


def _side_events(
    wide: WideLandmarks,
    frames: np.ndarray,
    pts_s: np.ndarray,
    video_id: str,
    side: str,
    config: Config,
) -> pd.DataFrame:
    landmarks = SIDE_LANDMARKS[side]
    heel = landmarks["heel"]
    foot_index = landmarks["foot_index"]
    ankle = landmarks["ankle"]
    hip = landmarks["hip"]

    forward = _forward_offset(wide, hip, heel, foot_index, config.visibility_threshold)
    contact_signal: np.ndarray | None = None
    contact_prominence = config.event_horizontal_prominence_frac * wide.width_px
    contact_kind = "forward"

    if forward is not None and np.isfinite(forward).sum() >= 3:
        candidate = _smooth(forward, config)
        if np.nanmax(candidate) - np.nanmin(candidate) >= contact_prominence:
            contact_signal = candidate
    if contact_signal is None:
        contact_signal = _vertical_signal(wide, heel, foot_index, ankle, config)
        contact_prominence = config.event_prominence_frac * wide.height_px
        contact_kind = "vertical"
    if contact_signal is None or np.isfinite(contact_signal).sum() < 3:
        return pd.DataFrame(columns=EVENT_COLUMNS)

    median_dt = float(np.median(np.diff(pts_s))) if len(pts_s) > 1 else 1.0
    distance = max(1, int(round(config.event_min_distance_s / median_dt)))
    peaks, properties = find_peaks(
        contact_signal,
        distance=distance,
        prominence=contact_prominence,
    )
    if len(peaks) == 0:
        return pd.DataFrame(columns=EVENT_COLUMNS)

    foot_bottom_y = _lowest_foot_y(wide, heel, foot_index, ankle, config.visibility_threshold)
    confidence = _min_visibility(wide, (hip, heel, foot_index))
    rows: list[dict[str, object]] = []
    for index, peak in enumerate(peaks):
        next_peak = int(peaks[index + 1]) if index + 1 < len(peaks) else None
        stop = next_peak if next_peak is not None else len(foot_bottom_y)
        toe_off = _toe_off(
            contact_signal if contact_kind == "forward" else foot_bottom_y,
            contact=int(peak),
            stop=stop,
            threshold=(
                0.02 * wide.width_px
                if contact_kind == "forward"
                else 0.015 * wide.height_px
            ),
            mode="minimum" if contact_kind == "forward" else "maximum",
        )
        stride_s = (
            float(pts_s[next_peak] - pts_s[peak]) if next_peak is not None else np.nan
        )
        rows.append(
            {
                "video_id": video_id,
                "side": side,
                "event_index": index,
                "contact_frame": int(frames[peak]),
                "contact_pts_s": float(pts_s[peak]),
                "contact_y_px": float(foot_bottom_y[peak]),
                "toe_off_frame": int(frames[toe_off]) if toe_off is not None else np.nan,
                "toe_off_pts_s": float(pts_s[toe_off]) if toe_off is not None else np.nan,
                "stance_s": float(pts_s[toe_off] - pts_s[peak])
                if toe_off is not None
                else np.nan,
                "stride_s": stride_s,
                "cadence_spm": 120.0 / stride_s
                if np.isfinite(stride_s) and stride_s > 0
                else np.nan,
                "prominence_px": float(properties["prominences"][index]),
                "confidence": float(confidence[peak]),
            }
        )
    return pd.DataFrame(rows)


def _forward_offset(
    wide: WideLandmarks,
    hip: str,
    heel: str,
    foot_index: str,
    threshold: float,
) -> np.ndarray | None:
    try:
        hip_visible = wide.visible(hip, threshold)
        heel_visible = wide.visible(heel, threshold)
        index_visible = wide.visible(foot_index, threshold)
        hip_x = wide.field("x", hip) * wide.width_px
        heel_x = wide.field("x", heel) * wide.width_px
        index_x = wide.field("x", foot_index) * wide.width_px
    except LandmarkError:
        return None
    if hip_visible.sum() < 3 or (heel_visible & index_visible).sum() < 3:
        return None

    foot_x = (heel_x + index_x) / 2.0
    valid = hip_visible & heel_visible & index_visible
    if valid.sum() < 3:
        return None
    direction = _walking_direction(hip_x, valid)
    if direction == 0:
        return None
    result = (foot_x - hip_x) * direction
    result[~valid] = np.nan
    return result


def _walking_direction(hip_x: np.ndarray, valid: np.ndarray) -> int:
    x = np.flatnonzero(valid)
    if len(x) < 3:
        return 0
    slope = np.polyfit(x, hip_x[valid], deg=1)[0]
    if abs(slope) < 0.01:
        return 0
    return -1 if slope < 0 else 1


def _vertical_signal(
    wide: WideLandmarks,
    heel: str,
    foot_index: str,
    ankle: str,
    config: Config,
) -> np.ndarray | None:
    foot_y = _lowest_foot_y(wide, heel, foot_index, ankle, config.visibility_threshold)
    if np.isfinite(foot_y).sum() < 3:
        return None
    return _smooth(foot_y, config)


def _smooth(values: np.ndarray, config: Config) -> np.ndarray:
    valid = np.isfinite(values)
    return _smooth_within_segments(values, valid, config)


def _min_visibility(wide: WideLandmarks, names: tuple[str, ...]) -> np.ndarray:
    arrays = []
    for name in names:
        try:
            arrays.append(wide.field("visibility", name))
        except LandmarkError:
            continue
    if not arrays:
        return np.zeros(wide.values.shape[0])
    return np.minimum.reduce(arrays)


def _lowest_foot_y(
    wide: WideLandmarks,
    heel: str,
    foot_index: str,
    ankle: str,
    threshold: float,
) -> np.ndarray:
    heel_y = wide.field("y", heel) * wide.height_px
    index_y = wide.field("y", foot_index) * wide.height_px
    ankle_y = wide.field("y", ankle) * wide.height_px
    heel_visible = wide.visible(heel, threshold)
    index_visible = wide.visible(foot_index, threshold)
    ankle_visible = wide.visible(ankle, threshold)

    result = np.full(len(heel_y), np.nan)
    both = heel_visible & index_visible
    result[both] = np.maximum(heel_y[both], index_y[both])
    result[heel_visible & ~index_visible] = heel_y[heel_visible & ~index_visible]
    result[index_visible & ~heel_visible] = index_y[index_visible & ~heel_visible]
    fallback = ~both & ankle_visible
    result[fallback] = ankle_y[fallback]
    return result


def _toe_off(
    values: np.ndarray,
    *,
    contact: int,
    stop: int,
    threshold: float,
    mode: str,
) -> int | None:
    """Reversal after the stance extreme between two contacts.

    Horizontal mode: forward offset peaks at contact, reaches a minimum during
    late stance, then rises at toe-off. Vertical mode: foot height reaches its
    lowest point (maximum image y) at foot flat, then rises at toe-off.
    """
    if contact >= stop:
        return None
    segment = values[contact:stop]
    if not np.isfinite(segment).any():
        return None
    if mode == "minimum":
        extreme = contact + int(np.nanargmin(segment))
        baseline = values[extreme]
        condition = lambda value: np.isfinite(value) and value > baseline + threshold
    else:
        extreme = contact + int(np.nanargmax(segment))
        baseline = values[extreme]
        condition = lambda value: np.isfinite(value) and value < baseline - threshold
    if extreme >= stop - 1:
        return None
    for index in range(extreme + 1, stop):
        if condition(values[index]):
            return index
    return None

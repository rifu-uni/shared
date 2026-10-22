"""Read the existing Tracker annotation for validation.

Tracker stores world coordinates, not pixels. The transform is the inverse of
the calibration written in the `.trk` file:

    x_px = xorigin + xscale * x_world
    y_px = yorigin - yscale * y_world

The y sign is inverted because Tracker's world y grows upward while image y
grows downward. `startframe` maps annotation time zero to the source video.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
import pandas as pd
from scipy.signal import find_peaks


class ManualError(ValueError):
    """Raised when the manual annotation cannot be parsed."""


@dataclass(frozen=True)
class TrackerCalibration:
    start_frame: int
    frame_count: int
    frame_rate: float
    x_origin: float
    y_origin: float
    x_scale: float
    y_scale: float

    def to_pixels(self, x_world: np.ndarray, y_world: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return (
            self.x_origin + self.x_scale * x_world,
            self.y_origin - self.y_scale * y_world,
        )


def load_tracker_calibration(path: Path) -> TrackerCalibration:
    if not path.is_file():
        raise ManualError(f"tracker file does not exist: {path}")
    root = ElementTree.parse(path).getroot()
    properties: dict[str, str] = {}
    for node in root.iter("property"):
        name = node.get("name")
        if name and node.text and name not in properties:
            properties[name] = node.text.strip()

    required = {
        "startframe": int,
        "frame_count": int,
        "frame_rate": float,
        "xorigin": float,
        "yorigin": float,
        "xscale": float,
        "yscale": float,
    }
    missing = sorted(key for key in required if key not in properties)
    if missing:
        raise ManualError(f"tracker file missing properties: {', '.join(missing)}")

    return TrackerCalibration(
        start_frame=int(properties["startframe"]),
        frame_count=int(properties["frame_count"]),
        frame_rate=float(properties["frame_rate"]),
        x_origin=float(properties["xorigin"]),
        y_origin=float(properties["yorigin"]),
        x_scale=float(properties["xscale"]),
        y_scale=float(properties["yscale"]),
    )


def load_manual_annotation(csv_path: Path, calibration: TrackerCalibration) -> pd.DataFrame:
    if not csv_path.is_file():
        raise ManualError(f"manual CSV does not exist: {csv_path}")
    raw = pd.read_csv(
        csv_path,
        skiprows=3,
        header=None,
        names=["t", "xA", "yA", "xB", "yB"],
        dtype=float,
    )
    if raw.empty:
        raise ManualError(f"manual CSV is empty: {csv_path}")

    xA, yA = calibration.to_pixels(raw["xA"].to_numpy(), raw["yA"].to_numpy())
    xB, yB = calibration.to_pixels(raw["xB"].to_numpy(), raw["yB"].to_numpy())
    frame = calibration.start_frame + np.rint(raw["t"].to_numpy() * calibration.frame_rate).astype(int)

    return pd.DataFrame(
        {
            "frame": frame,
            "pts_s": raw["t"].to_numpy(dtype=float),
            "waist_x_px": xA,
            "waist_y_px": yA,
            "ankle_x_px": xB,
            "ankle_y_px": yB,
        }
    )


def manual_contact_events(
    manual: pd.DataFrame,
    *,
    fps: float,
    min_distance_s: float = 0.35,
    depth_px: float = 8.0,
    halfwidth_s: float = 0.20,
) -> pd.DataFrame:
    """Ankle vertical lows in the manual annotation, as a contact proxy."""
    y = manual["ankle_y_px"].to_numpy(dtype=float)
    valid = np.isfinite(y)
    if valid.sum() < 3:
        return pd.DataFrame(columns=["contact_frame", "contact_pts_s", "contact_y_px"])

    distance = max(1, int(round(min_distance_s * fps)))
    halfwidth = max(1, int(round(halfwidth_s * fps)))
    candidates = []
    for index in range(1, len(y) - 1):
        if not (valid[index - 1] and valid[index] and valid[index + 1]):
            continue
        if not (y[index] >= y[index - 1] and y[index] > y[index + 1]):
            continue
        window = y[max(0, index - halfwidth) : index + halfwidth + 1]
        if np.nanmax(window) - y[index] < depth_px:
            continue
        candidates.append(index)

    kept: list[int] = []
    for index in sorted(candidates, key=lambda i: y[i], reverse=True):
        if all(abs(index - other) >= distance for other in kept):
            kept.append(index)
    kept.sort()

    if not kept:
        return pd.DataFrame(columns=["contact_frame", "contact_pts_s", "contact_y_px"])
    return pd.DataFrame(
        {
            "contact_frame": manual["frame"].to_numpy()[kept],
            "contact_pts_s": manual["pts_s"].to_numpy()[kept],
            "contact_y_px": y[kept],
        }
    )

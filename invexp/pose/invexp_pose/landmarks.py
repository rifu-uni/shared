"""Loading and reshaping the long landmark table."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .constants import LANDMARK_COLUMNS, SIDE_LANDMARKS


class LandmarkError(ValueError):
    """Raised when a landmark table does not match the pipeline contract."""


@dataclass(frozen=True)
class WideLandmarks:
    """One row per frame, landmark fields in a MultiIndex column space."""

    values: pd.DataFrame
    width_px: int
    height_px: int

    def field(self, field: str, name: str) -> np.ndarray:
        try:
            return self.values[(field, name)].to_numpy(dtype=float)
        except KeyError as exc:
            raise LandmarkError(f"landmark field not found: {field}/{name}") from exc

    def visible(self, name: str, threshold: float) -> np.ndarray:
        visibility = self.field("visibility", name)
        return np.isfinite(visibility) & (visibility >= threshold)


def load_landmarks(path: Path) -> WideLandmarks:
    if not path.is_file():
        raise LandmarkError(f"landmark table does not exist: {path}")
    frame = pd.read_csv(path)
    missing = sorted(set(LANDMARK_COLUMNS) - set(frame.columns))
    if missing:
        raise LandmarkError(f"landmark table missing columns: {', '.join(missing)}")
    if frame.empty:
        raise LandmarkError(f"landmark table is empty: {path}")

    meta = frame.groupby(["frame", "pts_s"], sort=True)[["width_px", "height_px"]].first()
    if meta.empty:
        raise LandmarkError(f"landmark table has no frames: {path}")
    width_px = int(meta["width_px"].iloc[0])
    height_px = int(meta["height_px"].iloc[0])
    if (meta["width_px"] != width_px).any() or (meta["height_px"] != height_px).any():
        raise LandmarkError("landmark table mixes frame sizes; split the video first")

    values = frame.pivot(
        index=["frame", "pts_s"],
        columns="name",
        values=["x", "y", "z", "visibility", "presence", "world_x", "world_y", "world_z"],
    ).sort_index()
    return WideLandmarks(values=values, width_px=width_px, height_px=height_px)


def side_visibility(wide: WideLandmarks, threshold: float) -> dict[str, float]:
    """Median visibility of the gait landmarks for each side."""
    scores: dict[str, float] = {}
    for side, landmarks in SIDE_LANDMARKS.items():
        visible_fractions = [
            float(np.mean(wide.visible(name, threshold)))
            for name in landmarks.values()
        ]
        scores[side] = float(np.median(visible_fractions))
    return scores


def choose_side(wide: WideLandmarks, threshold: float) -> tuple[str, dict[str, float]]:
    """Pick the side with the most visible gait landmarks.

    In a true sagittal view one side occludes the other. Picking a single side
    per video keeps angle series continuous; per-frame switching would create
    artificial jumps at every step.
    """
    scores = side_visibility(wide, threshold)
    side = max(scores, key=scores.get)
    if scores[side] <= 0:
        raise LandmarkError("no side has any visible gait landmarks")
    return side, scores

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def write_landmarks(
    path: Path,
    coords: dict[str, tuple[float, float]],
    *,
    frames: int = 1,
    width: int = 1000,
    height: int = 1000,
    visibility: float | dict[str, float] = 1.0,
) -> Path:
    rows = []
    for frame in range(frames):
        pts = frame / 120.0
        for name, (x, y) in coords.items():
            observed = (
                visibility.get(name, 1.0)
                if isinstance(visibility, dict)
                else visibility
            )
            rows.append(
                {
                    "video_id": "test",
                    "frame": frame,
                    "pts_s": pts,
                    "width_px": width,
                    "height_px": height,
                    "landmark_id": 0,
                    "name": name,
                    "x": x,
                    "y": y,
                    "z": 0.0,
                    "visibility": observed,
                    "presence": 1.0,
                    "world_x": np.nan,
                    "world_y": np.nan,
                    "world_z": np.nan,
                    "frame_detected": 1,
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False, compression="gzip")
    return path

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from invexp_pose.config import Config
from invexp_pose.events import detect_events
from invexp_pose.landmarks import load_landmarks


def test_two_contacts_from_synthetic_foot_trajectory(tmp_path) -> None:
    frames = 120
    index = np.arange(frames)
    y = 0.8 + 0.10 * np.cos(2 * np.pi * (index - 30) / 60)
    rows = []
    for frame in range(frames):
        for name, (x, yy) in {
            "left_ankle": (0.50, y[frame] - 0.05),
            "left_heel": (0.45, y[frame]),
            "left_foot_index": (0.55, y[frame]),
        }.items():
            rows.append(
                {
                    "video_id": "test",
                    "frame": frame,
                    "pts_s": frame / 120.0,
                    "width_px": 1000,
                    "height_px": 1000,
                    "landmark_id": 0,
                    "name": name,
                    "x": x,
                    "y": float(yy),
                    "z": 0.0,
                    "visibility": 1.0,
                    "presence": 1.0,
                    "world_x": np.nan,
                    "world_y": np.nan,
                    "world_z": np.nan,
                    "frame_detected": 1,
                }
            )
    path = tmp_path / "landmarks.csv.gz"
    pd.DataFrame(rows).to_csv(path, index=False, compression="gzip")
    wide = load_landmarks(path)
    events = detect_events(
        wide, video_id="test", config=Config(), sides=("left",)
    )

    left = events[events["side"] == "left"].reset_index(drop=True)
    assert len(left) == 2
    assert left["contact_frame"].tolist() == [30, 90]
    assert left["stride_s"].iloc[0] == pytest.approx(0.5, abs=1e-6)

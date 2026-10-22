from __future__ import annotations

import numpy as np
import pytest

from invexp_pose.config import Config
from invexp_pose.kinematics import angle_deg_from_arrays, compute_kinematics
from invexp_pose.landmarks import load_landmarks

from .conftest import write_landmarks


def test_angle_helper_right_angle() -> None:
    angle = angle_deg_from_arrays(1, 0, 0, 0, 0, 1)
    assert angle == pytest.approx(90.0)


def test_knee_flexion_from_synthetic_pose(tmp_path) -> None:
    coords = {
        "left_shoulder": (0.50, 0.10),
        "left_hip": (0.50, 0.30),
        "left_knee": (0.50, 0.60),
        "left_ankle": (0.80, 0.60),
        "left_heel": (0.85, 0.65),
        "left_foot_index": (0.80, 0.70),
    }
    path = write_landmarks(tmp_path / "landmarks.csv.gz", coords, frames=5)
    wide = load_landmarks(path)
    frame = compute_kinematics(
        wide, video_id="test", config=Config(), sides=("left",)
    )
    left = frame[frame["side"] == "left"]

    assert len(left) == 5
    assert left["knee_flexion_deg"].to_numpy() == pytest.approx(90.0, abs=0.2)
    assert left["hip_flexion_deg"].to_numpy() == pytest.approx(0.0, abs=0.2)
    assert left["valid"].all()


def test_low_visibility_is_not_interpolated(tmp_path) -> None:
    coords = {
        "left_shoulder": (0.50, 0.10),
        "left_hip": (0.50, 0.30),
        "left_knee": (0.50, 0.60),
        "left_ankle": (0.80, 0.60),
        "left_heel": (0.85, 0.65),
        "left_foot_index": (0.80, 0.70),
    }
    path = write_landmarks(
        tmp_path / "landmarks.csv.gz",
        coords,
        frames=5,
        visibility={"left_ankle": 0.1},
    )
    wide = load_landmarks(path)
    frame = compute_kinematics(
        wide, video_id="test", config=Config(visibility_threshold=0.5), sides=("left",)
    )
    assert not frame["valid"].any()

from __future__ import annotations

import numpy as np
import pandas as pd

from invexp_pose.imu import detect_impacts, load_imu_csv


def test_load_and_detect_impacts(tmp_path) -> None:
    time_s = np.arange(0, 2.0, 0.01)
    az = np.ones_like(time_s)
    az[50] = 5.0
    az[150] = 4.0
    path = tmp_path / "imu.csv"
    pd.DataFrame(
        {
            "time_s": time_s,
            "ax_g": np.zeros_like(time_s),
            "ay_g": np.zeros_like(time_s),
            "az_g": az,
        }
    ).to_csv(path, index=False)

    samples = load_imu_csv(path)
    impacts = detect_impacts(samples, min_height_g=2.0, min_distance_s=0.2)

    assert len(samples) == len(time_s)
    assert len(impacts) == 2
    assert impacts["peak_g"].tolist() == [5.0, 4.0]


def test_millisecond_time_column(tmp_path) -> None:
    path = tmp_path / "imu_ms.csv"
    pd.DataFrame(
        {
            "timestamp_ms": [0, 10, 20],
            "ax_g": [0, 1, 0],
            "ay_g": [0, 0, 0],
            "az_g": [1, 1, 1],
        }
    ).to_csv(path, index=False)
    samples = load_imu_csv(path)
    assert samples["time_s"].tolist() == [0.0, 0.01, 0.02]

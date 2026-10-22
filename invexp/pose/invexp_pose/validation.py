"""Validation against the existing Tracker annotation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .sync import match_nearest


class ValidationError(ValueError):
    """Raised when the manual and automatic tables cannot be compared."""


def compare_ankle_trajectory(
    manual: pd.DataFrame,
    kinematics: pd.DataFrame,
    *,
    side: str,
) -> dict[str, object]:
    """Compare the manual ankle marker with the MediaPipe foot point.

    The manual marker sits on the shoe/malleolus, close to the lowest foot point;
    MediaPipe's ankle joint centre is ~30-40 px higher. The comparison therefore
    uses the midpoint of heel and foot index and their lowest y. A constant
    anatomical offset remains, so centered RMSE is the primary shape metric.
    """
    pose = kinematics[kinematics["side"] == side][
        [
            "frame",
            "heel_x_px",
            "heel_y_px",
            "foot_index_x_px",
            "foot_index_y_px",
            "ankle_x_px",
            "ankle_y_px",
            "valid",
        ]
    ].copy()
    pose["foot_x_px"] = (pose["heel_x_px"] + pose["foot_index_x_px"]) / 2.0
    pose["foot_y_px"] = pose[["heel_y_px", "foot_index_y_px"]].max(axis=1)
    pose = pose[["frame", "foot_x_px", "foot_y_px", "valid"]]
    merged = manual.merge(pose, on="frame", how="inner", suffixes=("_manual", "_pose"))
    merged = merged[merged["valid"].fillna(False)]
    if len(merged) < 3:
        raise ValidationError("fewer than 3 overlapping frames with a valid pose")

    dx = merged["foot_x_px"].to_numpy(dtype=float) - merged["ankle_x_px"].to_numpy(dtype=float)
    dy = merged["foot_y_px"].to_numpy(dtype=float) - merged["ankle_y_px"].to_numpy(dtype=float)
    valid = np.isfinite(dx) & np.isfinite(dy)
    dx, dy = dx[valid], dy[valid]
    if len(dx) < 3:
        raise ValidationError("fewer than 3 finite ankle differences")

    centered_dx = dx - dx.mean()
    centered_dy = dy - dy.mean()
    return {
        "n": int(len(dx)),
        "mean_offset_px": {"x": float(dx.mean()), "y": float(dy.mean())},
        "raw_rmse_px": {
            "x": _rmse(dx),
            "y": _rmse(dy),
            "resultant": _rmse(np.hypot(dx, dy)),
        },
        "centered_rmse_px": {
            "x": _rmse(centered_dx),
            "y": _rmse(centered_dy),
            "resultant": _rmse(np.hypot(centered_dx, centered_dy)),
        },
        "bland_altman_px": {
            "x": _bland_altman(dx),
            "y": _bland_altman(dy),
        },
    }


def compare_contact_times(
    manual_events: pd.DataFrame,
    pose_events: pd.DataFrame,
    *,
    tolerance_s: float = 0.15,
) -> dict[str, object]:
    if manual_events.empty or pose_events.empty:
        raise ValidationError("manual or pose event table is empty")
    matches = match_nearest(
        manual_events,
        pose_events,
        reference_col="contact_pts_s",
        target_col="contact_pts_s",
        max_delay_s=tolerance_s,
    )
    delays = matches.loc[matches["matched"], "delay_s"].to_numpy(dtype=float)
    if len(delays) == 0:
        raise ValidationError(f"no event pairs within {tolerance_s:.3f} s")
    return {
        "n_manual": int(len(manual_events)),
        "n_pose": int(len(pose_events)),
        "n_matched": int(len(delays)),
        "tolerance_s": tolerance_s,
        "bias_s": float(delays.mean()),
        "sd_s": float(delays.std(ddof=1)) if len(delays) > 1 else 0.0,
        "loa_low_s": float(delays.mean() - 1.96 * delays.std(ddof=1))
        if len(delays) > 1
        else float(delays.mean()),
        "loa_high_s": float(delays.mean() + 1.96 * delays.std(ddof=1))
        if len(delays) > 1
        else float(delays.mean()),
    }


def _rmse(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(values**2)))


def _bland_altman(values: np.ndarray) -> dict[str, float]:
    mean = float(values.mean())
    sd = float(values.std(ddof=1)) if len(values) > 1 else 0.0
    return {
        "bias": mean,
        "sd": sd,
        "loa_low": mean - 1.96 * sd,
        "loa_high": mean + 1.96 * sd,
    }

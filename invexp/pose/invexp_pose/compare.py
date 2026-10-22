"""Join video-derived gait events with kinematics and IMU impacts."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .sync import impact_after_contact

ANGLE_COLUMNS = ("hip_flexion_deg", "knee_flexion_deg", "ankle_angle_deg")


class CompareError(ValueError):
    """Raised when tables cannot be joined under the declared tolerance."""


def attach_kinematics_at_contact(
    events: pd.DataFrame,
    kinematics: pd.DataFrame,
    *,
    tolerance_frames: int = 2,
) -> pd.DataFrame:
    """Attach joint angles from the frame nearest to each contact."""
    required_events = {"side", "contact_frame"}
    required_kinematics = {"side", "frame", *ANGLE_COLUMNS}
    if missing := sorted(required_events - set(events.columns)):
        raise CompareError(f"events missing columns: {', '.join(missing)}")
    if missing := sorted(required_kinematics - set(kinematics.columns)):
        raise CompareError(f"kinematics missing columns: {', '.join(missing)}")

    result = events.copy()
    for column in ANGLE_COLUMNS:
        result[f"contact_{column}"] = np.nan

    for side, side_events in result.groupby("side", sort=False):
        side_kinematics = kinematics[kinematics["side"] == side].sort_values("frame")
        if side_kinematics.empty:
            continue
        frames = side_kinematics["frame"].to_numpy(dtype=int)
        for event_index, contact_frame in side_events["contact_frame"].items():
            position = int(np.argmin(np.abs(frames - int(contact_frame))))
            if abs(int(frames[position]) - int(contact_frame)) > tolerance_frames:
                continue
            row = side_kinematics.iloc[position]
            for column in ANGLE_COLUMNS:
                result.at[event_index, f"contact_{column}"] = row[column]
    return result


def add_stride_rom(
    events: pd.DataFrame,
    kinematics: pd.DataFrame,
) -> pd.DataFrame:
    """Range of motion between each contact and the next contact of that side."""
    result = events.copy()
    for column in ANGLE_COLUMNS:
        result[f"{column.replace('_deg', '_rom_deg')}"] = np.nan

    for side, side_events in result.groupby("side", sort=False):
        side_kinematics = kinematics[kinematics["side"] == side].sort_values("frame")
        if side_kinematics.empty:
            continue
        ordered = side_events.sort_values("contact_frame")
        contacts = ordered["contact_frame"].to_numpy(dtype=int)
        frames = side_kinematics["frame"].to_numpy(dtype=int)
        for position, (event_index, row) in enumerate(ordered.iterrows()):
            contact_frame = int(row["contact_frame"])
            stop = contacts[position + 1] if position + 1 < len(contacts) else frames[-1]
            window = side_kinematics[
                (frames >= contact_frame) & (frames <= int(stop))
            ]
            for column in ANGLE_COLUMNS:
                values = window[column].to_numpy(dtype=float)
                values = values[np.isfinite(values)]
                if len(values) >= 2:
                    result.at[event_index, f"{column.replace('_deg', '_rom_deg')}"] = float(
                        values.max() - values.min()
                    )
    return result


def match_contacts_to_impacts(
    events: pd.DataFrame,
    impacts: pd.DataFrame,
    *,
    sensor: str | None = None,
    max_delay_s: float = 0.4,
) -> pd.DataFrame:
    matches = impact_after_contact(
        events,
        impacts,
        max_delay_s=max_delay_s,
        sensor=sensor,
    )
    if matches.empty:
        return matches
    result = events.reset_index(drop=True).copy()
    result["contact_index"] = np.arange(len(result))
    result = result.merge(
        matches,
        left_on="contact_index",
        right_on="contact_index",
        how="left",
        validate="one_to_one",
    )
    peak_by_index = impacts.set_index("impact_index")["peak_g"]
    result["impact_peak_g"] = result["impact_index"].map(peak_by_index)
    return result


def summarize_events(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(
            columns=[
                "side",
                "n_contacts",
                "median_stride_s",
                "median_cadence_spm",
                "median_stance_s",
            ]
        )
    rows = []
    for side, group in events.groupby("side", sort=True):
        rows.append(
            {
                "side": side,
                "n_contacts": len(group),
                "median_stride_s": float(group["stride_s"].median()),
                "median_cadence_spm": float(group["cadence_spm"].median()),
                "median_stance_s": float(group["stance_s"].median()),
            }
        )
    return pd.DataFrame(rows)


def summarize_delays(matched: pd.DataFrame) -> dict[str, float]:
    delays = matched.loc[matched["matched"], "delay_s"].dropna().to_numpy(dtype=float)
    if len(delays) == 0:
        return {
            "n": 0.0,
            "median_delay_s": float("nan"),
            "mean_delay_s": float("nan"),
            "sd_delay_s": float("nan"),
        }
    return {
        "n": float(len(delays)),
        "median_delay_s": float(np.median(delays)),
        "mean_delay_s": float(np.mean(delays)),
        "sd_delay_s": float(np.std(delays, ddof=1)) if len(delays) > 1 else 0.0,
    }

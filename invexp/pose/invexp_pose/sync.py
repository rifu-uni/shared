"""Event matching between video contacts, manual annotations and IMU impacts."""

from __future__ import annotations

import numpy as np
import pandas as pd


class SyncError(ValueError):
    """Raised when event tables cannot be matched under the requested window."""


def match_nearest(
    reference: pd.DataFrame,
    target: pd.DataFrame,
    *,
    reference_col: str,
    target_col: str,
    max_delay_s: float,
) -> pd.DataFrame:
    """Match every reference event to the nearest target event in time."""
    reference_values = _sorted_values(reference, reference_col)
    target_values = _sorted_values(target, target_col)
    rows: list[dict[str, object]] = []

    for ref_index, ref_time in reference_values:
        if len(target_values) == 0:
            rows.append(_unmatched(reference, ref_index, target, ref_time, max_delay_s))
            continue
        target_times = np.array([value for _, value in target_values])
        nearest = int(np.argmin(np.abs(target_times - ref_time)))
        target_index, target_time = target_values[nearest]
        delay = float(target_time - ref_time)
        rows.append(
            {
                "reference_index": ref_index,
                "reference_time_s": float(ref_time),
                "target_index": None if abs(delay) > max_delay_s else target_index,
                "target_time_s": None if abs(delay) > max_delay_s else float(target_time),
                "delay_s": delay if abs(delay) <= max_delay_s else np.nan,
                "matched": abs(delay) <= max_delay_s,
            }
        )
    return pd.DataFrame(rows)


def impact_after_contact(
    contacts: pd.DataFrame,
    impacts: pd.DataFrame,
    *,
    contact_col: str = "contact_pts_s",
    impact_col: str = "impact_time_s",
    max_delay_s: float = 0.4,
    sensor: str | None = None,
) -> pd.DataFrame:
    """Match each contact to the first impact at or after contact.

    A contact mechanically precedes its tibial impact peak. Searching forward
    avoids matching a contact to the previous step's impact when two feet are
    close in time.
    """
    events = impacts if sensor is None else impacts[impacts["sensor"] == sensor]
    impact_times = _sorted_values(events, impact_col)
    rows: list[dict[str, object]] = []

    for contact_index, contact_time in _sorted_values(contacts, contact_col):
        candidate = next(
            (
                (index, time)
                for index, time in impact_times
                if contact_time - 0.02 <= time <= contact_time + max_delay_s
            ),
            None,
        )
        impact_index = None
        if candidate is not None:
            impact_index = (
                events.iloc[candidate[0]]["impact_index"]
                if "impact_index" in events.columns
                else candidate[0]
            )
        rows.append(
            {
                "contact_index": contact_index,
                "contact_time_s": float(contact_time),
                "impact_index": impact_index,
                "impact_time_s": float(candidate[1]) if candidate else np.nan,
                "delay_s": float(candidate[1] - contact_time) if candidate else np.nan,
                "matched": candidate is not None,
            }
        )
    return pd.DataFrame(rows)


def offset_summary(matches: pd.DataFrame) -> dict[str, float]:
    delay = matches.loc[matches["matched"], "delay_s"].dropna().to_numpy(dtype=float)
    if len(delay) == 0:
        raise SyncError("no matched events; cannot estimate clock offset")
    return {
        "n": float(len(delay)),
        "median_delay_s": float(np.median(delay)),
        "mean_delay_s": float(np.mean(delay)),
        "sd_delay_s": float(np.std(delay, ddof=1)) if len(delay) > 1 else 0.0,
        "max_abs_delay_s": float(np.max(np.abs(delay))),
    }


def _sorted_values(frame: pd.DataFrame, column: str) -> list[tuple[int, float]]:
    if column not in frame.columns:
        raise SyncError(f"event table missing column: {column}")
    values = frame[column].to_numpy(dtype=float)
    indices = np.arange(len(frame))
    valid = np.isfinite(values)
    order = np.argsort(values[valid])
    return list(zip(indices[valid][order], values[valid][order]))


def _unmatched(
    reference: pd.DataFrame,
    reference_index: int,
    target: pd.DataFrame,
    reference_time: float,
    max_delay_s: float,
) -> dict[str, object]:
    return {
        "reference_index": reference_index,
        "reference_time_s": float(reference_time),
        "target_index": None,
        "target_time_s": None,
        "delay_s": np.nan,
        "matched": False,
    }

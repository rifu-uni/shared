"""Load ESP32/BMI160 CSV logs and detect impact peaks.

The firmware format is not frozen yet, so the loader accepts a small set of
common column names and converts time/acceleration units explicitly. It never
guesses silently: ambiguous columns raise.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

TIME_CANDIDATES = (
    "time_s",
    "t_s",
    "timestamp_s",
    "time_ms",
    "t_ms",
    "timestamp_ms",
    "time_us",
    "t_us",
    "timestamp_us",
    "time_ns",
    "t_ns",
    "timestamp_ns",
    "time",
    "timestamp",
    "host_time_s",
)
TIME_SCALE = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9}
G_TO_M_S2 = 9.80665


class ImuError(ValueError):
    """Raised when an IMU log does not match a supported schema."""


def load_imu_csv(
    path: Path,
    *,
    time_unit: str = "auto",
    accel_unit: str = "auto",
    sensor: str = "tibia",
) -> pd.DataFrame:
    if not path.is_file():
        raise ImuError(f"IMU CSV does not exist: {path}")
    raw = pd.read_csv(path)
    if raw.empty:
        raise ImuError(f"IMU CSV is empty: {path}")
    raw.columns = [str(column).strip() for column in raw.columns]

    time_column = _find_time_column(raw)
    accel_columns = _find_accel_columns(raw)
    time_s = _to_seconds(raw[time_column].to_numpy(dtype=float), time_column, time_unit)
    accel = raw[list(accel_columns)].to_numpy(dtype=float)
    accel_g = _to_g(accel, accel_columns, accel_unit)

    result = pd.DataFrame(
        {
            "time_s": time_s,
            "ax_g": accel_g[:, 0],
            "ay_g": accel_g[:, 1],
            "az_g": accel_g[:, 2],
            "sensor": raw["sensor_id"].astype(str)
            if "sensor_id" in raw.columns
            else sensor,
        }
    )
    result = result.sort_values(["sensor", "time_s"], kind="stable").reset_index(drop=True)
    result["magnitude_g"] = np.sqrt(
        result["ax_g"] ** 2 + result["ay_g"] ** 2 + result["az_g"] ** 2
    )
    if result.duplicated(["sensor", "time_s"]).any():
        raise ImuError("duplicate timestamps for a sensor; fix the logger before analysis")
    return result


def detect_impacts(
    samples: pd.DataFrame,
    *,
    min_height_g: float = 2.0,
    min_distance_s: float = 0.25,
    prominence_g: float = 0.5,
) -> pd.DataFrame:
    """Detect impact peaks per sensor on the vector magnitude."""
    required = {"sensor", "time_s", "magnitude_g"}
    missing = sorted(required - set(samples.columns))
    if missing:
        raise ImuError(f"IMU samples missing columns: {', '.join(missing)}")

    rows: list[pd.DataFrame] = []
    for sensor, group in samples.groupby("sensor", sort=True):
        group = group.sort_values("time_s")
        time_s = group["time_s"].to_numpy(dtype=float)
        magnitude = group["magnitude_g"].to_numpy(dtype=float)
        valid = np.isfinite(magnitude)
        if valid.sum() < 3:
            continue
        if not valid.all():
            magnitude = np.interp(time_s, time_s[valid], magnitude[valid])
        median_dt = float(np.median(np.diff(time_s))) if len(time_s) > 1 else 1.0
        distance = max(1, int(round(min_distance_s / median_dt)))
        peaks, properties = find_peaks(
            magnitude,
            height=min_height_g,
            prominence=prominence_g,
            distance=distance,
        )
        if len(peaks) == 0:
            continue
        rows.append(
            pd.DataFrame(
                {
                    "sensor": sensor,
                    "impact_index": group.index.to_numpy()[peaks],
                    "impact_time_s": time_s[peaks],
                    "peak_g": magnitude[peaks],
                    "prominence_g": properties["prominences"],
                }
            )
        )
    if not rows:
        return pd.DataFrame(
            columns=["sensor", "impact_index", "impact_time_s", "peak_g", "prominence_g"]
        )
    return pd.concat(rows, ignore_index=True).sort_values(
        ["sensor", "impact_time_s"]
    ).reset_index(drop=True)


def summarize_impacts(impacts: pd.DataFrame) -> pd.DataFrame:
    if impacts.empty:
        return pd.DataFrame(
            columns=["sensor", "n_impacts", "median_peak_g", "median_interval_s"]
        )
    rows = []
    for sensor, group in impacts.groupby("sensor", sort=True):
        intervals = np.diff(group["impact_time_s"].to_numpy(dtype=float))
        rows.append(
            {
                "sensor": sensor,
                "n_impacts": len(group),
                "median_peak_g": float(group["peak_g"].median()),
                "median_interval_s": float(np.median(intervals)) if len(intervals) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def _find_time_column(frame: pd.DataFrame) -> str:
    lookup = {column.lower(): column for column in frame.columns}
    for candidate in TIME_CANDIDATES:
        if candidate in lookup:
            return lookup[candidate]
    raise ImuError(
        f"no time column found; supported names: {', '.join(TIME_CANDIDATES)}"
    )


def _find_accel_columns(frame: pd.DataFrame) -> tuple[str, str, str]:
    lookup = {column.lower(): column for column in frame.columns}
    triples = (
        ("ax_g", "ay_g", "az_g"),
        ("ax", "ay", "az"),
        ("ax_m_s2", "ay_m_s2", "az_m_s2"),
        ("ax_ms2", "ay_ms2", "az_ms2"),
        ("accel_x", "accel_y", "accel_z"),
        ("a_x", "a_y", "a_z"),
        ("acc_x", "acc_y", "acc_z"),
    )
    for triple in triples:
        if all(name in lookup for name in triple):
            return tuple(lookup[name] for name in triple)  # type: ignore[return-value]
    raise ImuError(
        "no accelerometer triple found; expected ax/ay/az, ax_g/ay_g/az_g "
        "or accel_x/accel_y/accel_z"
    )


def _to_seconds(values: np.ndarray, column: str, unit: str) -> np.ndarray:
    if unit == "auto":
        lower = column.lower()
        unit = next((name for name in ("ns", "us", "ms") if lower.endswith(f"_{name}")), "s")
    if unit not in TIME_SCALE:
        raise ImuError(f"unsupported time unit: {unit}")
    seconds = values * TIME_SCALE[unit]
    if np.any(np.diff(seconds) < 0):
        raise ImuError(f"time column is not monotonic: {column}")
    return seconds


def _to_g(accel: np.ndarray, columns: tuple[str, str, str], unit: str) -> np.ndarray:
    if unit == "auto":
        joined = " ".join(column.lower() for column in columns)
        unit = "m_s2" if ("m_s2" in joined or "m/s2" in joined or "ms2" in joined) else "g"
    if unit == "g":
        return accel
    if unit in {"m_s2", "m/s2"}:
        return accel / G_TO_M_S2
    raise ImuError(f"unsupported acceleration unit: {unit}")

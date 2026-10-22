"""Small, human-readable run reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .compare import summarize_events


def render_report(
    *,
    video_id: str,
    metadata: dict[str, Any],
    events: pd.DataFrame,
    kinematics: pd.DataFrame,
    validation: dict[str, Any] | None = None,
) -> str:
    lines = [f"# Pose pipeline: {video_id}", ""]
    lines.append(f"- Frames processed: {metadata.get('frames_processed', '?')}")
    lines.append(f"- Frames detected: {metadata.get('frames_detected', '?')}")
    rate = metadata.get("detection_rate")
    if isinstance(rate, (int, float)):
        lines.append(f"- Detection rate: {100 * rate:.1f} %")
    lines.append(f"- Model: {metadata.get('model', '?')}")
    lines.append(f"- Elapsed: {metadata.get('elapsed_s', '?')} s")
    lines.append("")

    summary = summarize_events(events)
    if summary.empty:
        lines.append("No contact events detected.")
    else:
        lines.append("## Contacts")
        lines.append("")
        lines.append("```")
        lines.append(summary.to_string(index=False))
        lines.append("```")
        lines.append("")

    if not kinematics.empty:
        lines.append("## Kinematics")
        lines.append("")
        lines.append(
            f"- Valid frames: {int(kinematics['valid'].sum())} / {len(kinematics)}"
        )
        for column in ("knee_flexion_deg", "hip_flexion_deg", "ankle_angle_deg"):
            values = kinematics[column].dropna()
            if not values.empty:
                lines.append(
                    f"- {column}: median {values.median():.1f}°, "
                    f"range {values.min():.1f}–{values.max():.1f}°"
                )
        lines.append("")

    if validation is not None:
        lines.append("## Manual validation")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(validation, indent=2))
        lines.append("```")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_report(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)

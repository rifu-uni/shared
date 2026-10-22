"""End-to-end orchestration: video -> landmarks -> kinematics/events -> report."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .config import Config
from .events import detect_events
from .kinematics import compute_kinematics
from .landmarks import choose_side, load_landmarks, side_visibility
from .pose import extract_video
from .report import render_report, write_report


def derive_landmarks(
    landmarks_path: Path,
    *,
    video_id: str,
    config: Config,
    output_dir: Path,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    if metadata is None:
        metadata = _read_sidecar_metadata(landmarks_path)
    wide = load_landmarks(landmarks_path)
    selected_side, scores = choose_side(wide, config.visibility_threshold)

    kinematics = compute_kinematics(wide, video_id=video_id, config=config)
    events = detect_events(wide, video_id=video_id, config=config)

    output_dir.mkdir(parents=True, exist_ok=True)
    kinematics_path = output_dir / f"{video_id}_kinematics.csv.gz"
    events_path = output_dir / f"{video_id}_events.csv"
    kinematics.to_csv(kinematics_path, index=False, compression="gzip")
    events.to_csv(events_path, index=False)

    run_metadata: dict[str, object] = {
        "video_id": video_id,
        "landmarks": str(landmarks_path),
        "selected_side": selected_side,
        "side_visibility": scores,
        "frames": int(wide.values.shape[0]),
        "kinematics_rows": int(len(kinematics)),
        "valid_kinematics_rows": int(kinematics["valid"].sum()),
        "contacts": int(len(events)),
        "contacts_by_side": events["side"].value_counts().to_dict() if not events.empty else {},
    }
    if metadata is not None:
        run_metadata["pose"] = metadata

    metadata_path = output_dir / f"{video_id}_run.json"
    metadata_path.write_text(json.dumps(run_metadata, indent=2) + "\n")

    report_path = output_dir / f"{video_id}_report.md"
    validation_path = output_dir / f"{video_id}_validation.json"
    validation = json.loads(validation_path.read_text()) if validation_path.is_file() else None
    write_report(
        report_path,
        render_report(
            video_id=video_id,
            metadata=metadata or {},
            events=events,
            kinematics=kinematics,
            validation=validation,
        ),
    )
    return {
        "metadata": run_metadata,
        "kinematics": kinematics_path,
        "events": events_path,
        "report": report_path,
        "run_metadata": metadata_path,
    }


def run_video(
    video_path: Path,
    *,
    video_id: str,
    config: Config,
    landmarks_dir: Path,
    output_dir: Path,
    start_s: float | None = None,
    end_s: float | None = None,
    stride: int = 1,
    limit: int | None = None,
) -> dict[str, object]:
    landmarks_path = landmarks_dir / f"{video_id}_landmarks.csv.gz"
    pose_metadata = extract_video(
        video_path,
        landmarks_path,
        video_id=video_id,
        config=config,
        start_s=start_s,
        end_s=end_s,
        stride=stride,
        limit=limit,
    )
    derived = derive_landmarks(
        landmarks_path,
        video_id=video_id,
        config=config,
        output_dir=output_dir,
        metadata=pose_metadata,
    )
    derived["landmarks"] = landmarks_path
    return derived


def write_events(path: Path, events: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    events.to_csv(path, index=False)


def _read_sidecar_metadata(landmarks_path: Path) -> dict[str, object] | None:
    sidecar = landmarks_path.with_suffix("").with_suffix(".json")
    if not sidecar.is_file():
        return None
    return json.loads(sidecar.read_text())

"""Command line entry point for the InvExp pose pipeline."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .compare import (
    add_stride_rom,
    attach_kinematics_at_contact,
    match_contacts_to_impacts,
    summarize_delays,
)
from .config import (
    DEFAULT_DATA_DIR,
    DEFAULT_OUTPUT_DIR,
    POSE_DIR,
    Config,
    load_config,
)
from .imu import detect_impacts, load_imu_csv, summarize_impacts
from .manual import (
    load_manual_annotation,
    load_tracker_calibration,
    manual_contact_events,
)
from .overlay import OverlayError, render_overlay
from .pipeline import derive_landmarks, run_video
from .pose import ensure_model, extract_video
from .validation import compare_ankle_trajectory, compare_contact_times
from .video import probe

DEFAULT_CONFIG = POSE_DIR / "configs" / "walk.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.function(args)
    except Exception as error:  # noqa: BLE001 - CLI boundary: report, do not traceback
        print(f"error: {error}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="invexp_pose",
        description="Inference-only pose, gait events and IMU comparison pipeline.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    probe_parser = sub.add_parser("probe", help="print video metadata")
    probe_parser.add_argument("video", type=Path)
    probe_parser.set_defaults(function=_probe)

    extract_parser = sub.add_parser("extract", help="run MediaPipe and write landmarks")
    extract_parser.add_argument("video", type=Path)
    extract_parser.add_argument("--video-id")
    extract_parser.add_argument("--landmarks-dir", type=Path)
    extract_parser.add_argument("--start", type=float, dest="start_s")
    extract_parser.add_argument("--end", type=float, dest="end_s")
    extract_parser.add_argument("--stride", type=int, default=1)
    extract_parser.add_argument("--limit", type=int)
    _add_config(extract_parser)
    extract_parser.set_defaults(function=_extract)

    derive_parser = sub.add_parser("derive", help="landmarks -> kinematics + events")
    derive_parser.add_argument("landmarks", type=Path)
    derive_parser.add_argument("--video-id")
    derive_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    _add_config(derive_parser)
    derive_parser.set_defaults(function=_derive)

    run_parser = sub.add_parser("run", help="video -> landmarks -> kinematics + events")
    run_parser.add_argument("video", type=Path)
    run_parser.add_argument("--video-id")
    run_parser.add_argument("--landmarks-dir", type=Path)
    run_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    run_parser.add_argument("--start", type=float, dest="start_s")
    run_parser.add_argument("--end", type=float, dest="end_s")
    run_parser.add_argument("--stride", type=int, default=1)
    run_parser.add_argument("--limit", type=int)
    _add_config(run_parser)
    run_parser.set_defaults(function=_run)

    batch_parser = sub.add_parser("batch", help="run every walkTest video")
    batch_parser.add_argument("--pattern", default="*.MOV")
    batch_parser.add_argument("--video-dir", type=Path)
    batch_parser.add_argument("--landmarks-dir", type=Path)
    batch_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    batch_parser.add_argument("--force", action="store_true")
    batch_parser.add_argument("--start", type=float, dest="start_s")
    batch_parser.add_argument("--end", type=float, dest="end_s")
    batch_parser.add_argument("--stride", type=int, default=1)
    batch_parser.add_argument("--limit", type=int)
    _add_config(batch_parser)
    batch_parser.set_defaults(function=_batch)

    overlay_parser = sub.add_parser(
        "overlay", help="render landmarks and events over the source video"
    )
    overlay_parser.add_argument("--video", type=Path)
    overlay_parser.add_argument("--video-id")
    overlay_parser.add_argument("--landmarks", type=Path)
    overlay_parser.add_argument("--events", type=Path)
    overlay_parser.add_argument("--out", type=Path)
    overlay_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    overlay_parser.add_argument("--landmarks-dir", type=Path)
    overlay_parser.add_argument("--start", type=float, dest="start_s")
    overlay_parser.add_argument("--end", type=float, dest="end_s")
    overlay_parser.add_argument("--full", action="store_true")
    overlay_parser.add_argument("--padding", type=float, default=1.0)
    overlay_parser.add_argument("--max-width", type=int, default=1280)
    overlay_parser.add_argument("--crf", type=int, default=22)
    overlay_parser.add_argument("--force", action="store_true")
    overlay_parser.set_defaults(function=_overlay)

    overlay_batch_parser = sub.add_parser(
        "overlay-batch", help="render overlays for every run in the output dir"
    )
    overlay_batch_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    overlay_batch_parser.add_argument("--landmarks-dir", type=Path)
    overlay_batch_parser.add_argument("--start", type=float, dest="start_s")
    overlay_batch_parser.add_argument("--end", type=float, dest="end_s")
    overlay_batch_parser.add_argument("--full", action="store_true")
    overlay_batch_parser.add_argument("--padding", type=float, default=1.0)
    overlay_batch_parser.add_argument("--max-width", type=int, default=1280)
    overlay_batch_parser.add_argument("--crf", type=int, default=22)
    overlay_batch_parser.add_argument("--force", action="store_true")
    overlay_batch_parser.set_defaults(function=_overlay_batch)

    validate_parser = sub.add_parser("validate", help="compare pose with Tracker annotation")
    validate_parser.add_argument("--kinematics", type=Path, required=True)
    validate_parser.add_argument("--events", type=Path, required=True)
    validate_parser.add_argument("--trk", type=Path, required=True)
    validate_parser.add_argument("--manual-csv", type=Path, required=True)
    validate_parser.add_argument("--side", choices=("left", "right"), default="right")
    validate_parser.add_argument("--tolerance-s", type=float, default=0.15)
    validate_parser.add_argument("--out", type=Path, required=True)
    validate_parser.set_defaults(function=_validate)

    imu_parser = sub.add_parser("imu", help="load IMU CSV and detect impacts")
    imu_parser.add_argument("--csv", type=Path, required=True)
    imu_parser.add_argument("--sensor", default="tibia")
    imu_parser.add_argument("--min-height-g", type=float, default=2.0)
    imu_parser.add_argument("--min-distance-s", type=float, default=0.25)
    imu_parser.add_argument("--prominence-g", type=float, default=0.5)
    imu_parser.add_argument("--out", type=Path, required=True)
    imu_parser.set_defaults(function=_imu)

    compare_parser = sub.add_parser("compare", help="join events, kinematics and impacts")
    compare_parser.add_argument("--events", type=Path, required=True)
    compare_parser.add_argument("--kinematics", type=Path, required=True)
    compare_parser.add_argument("--impacts", type=Path, required=True)
    compare_parser.add_argument("--sensor", default="tibia")
    compare_parser.add_argument("--max-delay-s", type=float, default=0.4)
    compare_parser.add_argument("--out", type=Path, required=True)
    compare_parser.set_defaults(function=_compare)

    model_parser = sub.add_parser("download-models", help="download and verify pose models")
    model_parser.add_argument("--model", choices=("lite", "full", "heavy"), default="heavy")
    model_parser.set_defaults(function=_download_models)

    return parser


def _add_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--model", choices=("lite", "full", "heavy"))


def _load_config(args: argparse.Namespace) -> Config:
    overrides = {}
    model = getattr(args, "model", None)
    if model is not None:
        overrides["model"] = model
    return load_config(args.config, **overrides)


def _landmarks_dir(args: argparse.Namespace) -> Path:
    if getattr(args, "landmarks_dir", None) is not None:
        return args.landmarks_dir
    data_dir = Path(os.environ.get("INVEXP_DATA_DIR", DEFAULT_DATA_DIR)).expanduser()
    return data_dir / "derived" / "pose"


def _video_id(args: argparse.Namespace) -> str:
    return getattr(args, "video_id", None) or args.video.stem


def _probe(args: argparse.Namespace) -> int:
    print(_json(asdict(probe(args.video))))
    return 0


def _extract(args: argparse.Namespace) -> int:
    config = _load_config(args)
    video_id = _video_id(args)
    output_path = _landmarks_dir(args) / f"{video_id}_landmarks.csv.gz"
    metadata = extract_video(
        args.video,
        output_path,
        video_id=video_id,
        config=config,
        start_s=args.start_s,
        end_s=args.end_s,
        stride=args.stride,
        limit=args.limit,
    )
    print(_json(metadata))
    return 0


def _derive(args: argparse.Namespace) -> int:
    config = _load_config(args)
    video_id = _video_id(args)
    result = derive_landmarks(
        args.landmarks,
        video_id=video_id,
        config=config,
        output_dir=args.output_dir,
    )
    print(_json({key: str(value) for key, value in result.items()}))
    return 0


def _run(args: argparse.Namespace) -> int:
    config = _load_config(args)
    video_id = _video_id(args)
    result = run_video(
        args.video,
        video_id=video_id,
        config=config,
        landmarks_dir=_landmarks_dir(args),
        output_dir=args.output_dir,
        start_s=args.start_s,
        end_s=args.end_s,
        stride=args.stride,
        limit=args.limit,
    )
    print(_json({key: str(value) for key, value in result.items()}))
    return 0


def _batch(args: argparse.Namespace) -> int:
    data_dir = Path(os.environ.get("INVEXP_DATA_DIR", DEFAULT_DATA_DIR)).expanduser()
    video_dir = args.video_dir or (data_dir / "walkTest")
    videos = sorted(video_dir.glob(args.pattern))
    if not videos:
        print(f"no videos matching {args.pattern} in {video_dir}", file=sys.stderr)
        return 1

    config = _load_config(args)
    failures = 0
    for video in videos:
        video_id = video.stem
        expected = args.output_dir / f"{video_id}_events.csv"
        if expected.exists() and not args.force:
            print(f"skip {video_id}: {expected} exists")
            continue
        print(f"run {video_id}: {video}")
        try:
            run_video(
                video,
                video_id=video_id,
                config=config,
                landmarks_dir=_landmarks_dir(args),
                output_dir=args.output_dir,
                start_s=args.start_s,
                end_s=args.end_s,
                stride=args.stride,
                limit=args.limit,
            )
        except Exception as error:  # noqa: BLE001 - one bad clip must not kill the batch
            failures += 1
            print(f"error {video_id}: {error}", file=sys.stderr)
    _aggregate_batch(args.output_dir)
    return 1 if failures else 0


def _aggregate_batch(output_dir: Path) -> None:
    event_files = sorted(output_dir.glob("*_events.csv"))
    if event_files:
        events = pd.concat(
            (pd.read_csv(path, dtype={"video_id": str}) for path in event_files),
            ignore_index=True,
        )
        events.to_csv(output_dir / "events_all.csv", index=False)

    rows = []
    for path in sorted(output_dir.glob("*_run.json")):
        metadata = json.loads(path.read_text())
        pose = metadata.get("pose", {})
        rows.append(
            {
                "video_id": metadata.get("video_id"),
                "frames_processed": pose.get("frames_processed"),
                "frames_detected": pose.get("frames_detected"),
                "detection_rate": pose.get("detection_rate"),
                "contacts": metadata.get("contacts"),
                "selected_side": metadata.get("selected_side"),
            }
        )
    if rows:
        pd.DataFrame(rows).to_csv(output_dir / "summary.csv", index=False)


def _overlay(args: argparse.Namespace) -> int:
    video_id = args.video_id or (args.video.stem if args.video else None)
    if video_id is None:
        raise OverlayError("--video-id is required when --video is omitted")
    _overlay_one(args, video_id, skip_existing=False)
    return 0


def _overlay_batch(args: argparse.Namespace) -> int:
    runs = sorted(args.output_dir.glob("*_run.json"))
    if not runs:
        print(f"no run metadata in {args.output_dir}", file=sys.stderr)
        return 1

    failures = 0
    for run_path in runs:
        video_id = run_path.name.removesuffix("_run.json")
        try:
            _overlay_one(args, video_id, skip_existing=True)
        except Exception as error:  # noqa: BLE001 - one bad clip must not kill the batch
            failures += 1
            print(f"error {video_id}: {error}", file=sys.stderr)
    return 1 if failures else 0


def _overlay_one(
    args: argparse.Namespace,
    video_id: str,
    *,
    skip_existing: bool,
) -> None:
    video, landmarks, events, output = _overlay_inputs(args, video_id)
    if output.exists() and not args.force:
        if skip_existing:
            print(f"skip {video_id}: {output} exists")
            return
        raise OverlayError(f"output exists: {output}; pass --force to replace it")

    print(f"overlay {video_id}: {video}")
    result = render_overlay(
        video,
        landmarks,
        output,
        video_id=video_id,
        events_path=events,
        start_s=args.start_s,
        end_s=args.end_s,
        full=args.full,
        padding_s=args.padding,
        max_width=args.max_width,
        crf=args.crf,
    )
    print(_json(asdict(result)))


def _overlay_inputs(
    args: argparse.Namespace,
    video_id: str,
) -> tuple[Path, Path, Path | None, Path]:
    output_dir = args.output_dir
    run_path = output_dir / f"{video_id}_run.json"
    metadata = json.loads(run_path.read_text()) if run_path.is_file() else {}

    video = getattr(args, "video", None)
    if video is None:
        recorded = metadata.get("pose", {}).get("video", {}).get("path")
        if recorded and Path(recorded).is_file():
            video = Path(recorded)
        else:
            data_dir = Path(os.environ.get("INVEXP_DATA_DIR", DEFAULT_DATA_DIR)).expanduser()
            video = data_dir / "walkTest" / f"{video_id}.MOV"

    landmarks = getattr(args, "landmarks", None)
    if landmarks is None:
        recorded = metadata.get("landmarks")
        landmarks = Path(recorded) if recorded else None
        if landmarks is None or not landmarks.is_file():
            landmarks = _landmarks_dir(args) / f"{video_id}_landmarks.csv.gz"
    if not landmarks.is_file():
        raise OverlayError(f"landmark table does not exist: {landmarks}")

    events = getattr(args, "events", None)
    if events is None:
        candidate = output_dir / f"{video_id}_events.csv"
        events = candidate if candidate.is_file() else None

    output = getattr(args, "out", None) or output_dir / f"{video_id}_overlay.mp4"
    return video, landmarks, events, output


def _validate(args: argparse.Namespace) -> int:
    calibration = load_tracker_calibration(args.trk)
    manual = load_manual_annotation(args.manual_csv, calibration)
    kinematics = pd.read_csv(args.kinematics)
    events = pd.read_csv(args.events)
    pose_events = events[events["side"] == args.side]
    manual_events = manual_contact_events(manual, fps=calibration.frame_rate)
    manual_events["contact_pts_s"] += calibration.start_frame / calibration.frame_rate

    result = {
        "side": args.side,
        "tracker_start_frame": calibration.start_frame,
        "trajectory": compare_ankle_trajectory(manual, kinematics, side=args.side),
        "contacts": compare_contact_times(
            manual_events, pose_events, tolerance_s=args.tolerance_s
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(_json(result) + "\n")
    print(_json(result))
    return 0


def _imu(args: argparse.Namespace) -> int:
    samples = load_imu_csv(args.csv, sensor=args.sensor)
    impacts = detect_impacts(
        samples,
        min_height_g=args.min_height_g,
        min_distance_s=args.min_distance_s,
        prominence_g=args.prominence_g,
    )
    summary = summarize_impacts(impacts)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    samples.to_csv(args.out.with_name(f"{args.out.stem}_samples.csv"), index=False)
    impacts.to_csv(args.out.with_name(f"{args.out.stem}_impacts.csv"), index=False)
    print(_json({"summary": summary.to_dict(orient="records")}))
    return 0


def _compare(args: argparse.Namespace) -> int:
    events = pd.read_csv(args.events)
    kinematics = pd.read_csv(args.kinematics)
    impacts = pd.read_csv(args.impacts)

    enriched = attach_kinematics_at_contact(events, kinematics)
    enriched = add_stride_rom(enriched, kinematics)
    matched = match_contacts_to_impacts(
        enriched,
        impacts,
        sensor=args.sensor,
        max_delay_s=args.max_delay_s,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    matched.to_csv(args.out, index=False)
    print(_json({"rows": len(matched), "delays": summarize_delays(matched)}))
    return 0


def _download_models(args: argparse.Namespace) -> int:
    config = Config(model=args.model)
    path = ensure_model(config)
    print(path)
    return 0


def _json(value: object) -> str:
    return json.dumps(value, indent=2, default=str)


if __name__ == "__main__":
    raise SystemExit(main())

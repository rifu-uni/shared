from __future__ import annotations

import av
import numpy as np
import pandas as pd

from invexp_pose.constants import LANDMARK_NAMES
from invexp_pose.overlay import render_overlay
from invexp_pose.video import probe


def test_overlay_encodes_landmarks_and_events(tmp_path) -> None:
    video_path = tmp_path / "tiny.mov"
    _write_video(video_path)

    landmarks_path = tmp_path / "tiny_landmarks.csv.gz"
    rows = []
    for frame in range(3):
        for landmark_id, name in enumerate(LANDMARK_NAMES):
            rows.append(
                {
                    "video_id": "tiny",
                    "frame": frame,
                    "pts_s": frame / 30.0,
                    "width_px": 64,
                    "height_px": 64,
                    "landmark_id": landmark_id,
                    "name": name,
                    "x": 0.25 + 0.05 * landmark_id / len(LANDMARK_NAMES),
                    "y": 0.20 + 0.02 * frame,
                    "z": 0.0,
                    "visibility": 1.0,
                    "presence": 1.0,
                    "world_x": 0.0,
                    "world_y": 0.0,
                    "world_z": 0.0,
                    "frame_detected": 1,
                }
            )
    pd.DataFrame(rows).to_csv(landmarks_path, index=False, compression="gzip")

    events_path = tmp_path / "tiny_events.csv"
    pd.DataFrame(
        [
            {
                "video_id": "tiny",
                "side": "left",
                "event_index": 0,
                "contact_frame": 1,
                "contact_pts_s": 1 / 30,
                "toe_off_frame": 2,
                "toe_off_pts_s": 2 / 30,
            }
        ]
    ).to_csv(events_path, index=False)

    output_path = tmp_path / "tiny_overlay.mp4"
    result = render_overlay(
        video_path,
        landmarks_path,
        output_path,
        video_id="tiny",
        events_path=events_path,
        max_width=64,
        padding_s=0.0,
    )

    assert result.frames_encoded == 3
    assert output_path.is_file() and output_path.stat().st_size > 0
    assert probe(output_path).frame_count == 3


def _write_video(path) -> None:
    container = av.open(str(path), mode="w")
    stream = container.add_stream("mpeg4", rate=30)
    stream.width = 64
    stream.height = 64
    stream.pix_fmt = "yuv420p"
    for index in range(3):
        image = np.full((64, 64, 3), 32 + index * 16, dtype=np.uint8)
        frame = av.VideoFrame.from_ndarray(image, format="rgb24")
        frame.pts = index
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()

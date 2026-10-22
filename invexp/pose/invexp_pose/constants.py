"""MediaPipe Pose Landmarker landmark names and anatomical groups."""

from __future__ import annotations

LANDMARK_NAMES: tuple[str, ...] = (
    "nose",
    "left_eye_inner",
    "left_eye",
    "left_eye_outer",
    "right_eye_inner",
    "right_eye",
    "right_eye_outer",
    "left_ear",
    "right_ear",
    "mouth_left",
    "mouth_right",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_pinky",
    "right_pinky",
    "left_index",
    "right_index",
    "left_thumb",
    "right_thumb",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "left_heel",
    "right_heel",
    "left_foot_index",
    "right_foot_index",
)

LANDMARK_INDEX: dict[str, int] = {name: i for i, name in enumerate(LANDMARK_NAMES)}

# Anatomical groups used by the kinematics stage. Only these landmarks are
# required; eye/hand landmarks are stored but not used for gait angles.
SIDE_LANDMARKS: dict[str, dict[str, str]] = {
    "left": {
        "shoulder": "left_shoulder",
        "hip": "left_hip",
        "knee": "left_knee",
        "ankle": "left_ankle",
        "heel": "left_heel",
        "foot_index": "left_foot_index",
    },
    "right": {
        "shoulder": "right_shoulder",
        "hip": "right_hip",
        "knee": "right_knee",
        "ankle": "right_ankle",
        "heel": "right_heel",
        "foot_index": "right_foot_index",
    },
}

ALL_SIDES: tuple[str, ...] = ("left", "right")

# Landmark rows are written with these columns. Keep this tuple in sync with
# `write_landmarks` and `load_landmarks`.
LANDMARK_COLUMNS: tuple[str, ...] = (
    "video_id",
    "frame",
    "pts_s",
    "width_px",
    "height_px",
    "landmark_id",
    "name",
    "x",
    "y",
    "z",
    "visibility",
    "presence",
    "world_x",
    "world_y",
    "world_z",
    "frame_detected",
)

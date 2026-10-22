"""Pipeline configuration parsed once at the CLI boundary."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

import yaml

PACKAGE_DIR = Path(__file__).resolve().parent
POSE_DIR = PACKAGE_DIR.parent
INVEXP_DIR = POSE_DIR.parent
REPO_ROOT = INVEXP_DIR.parent
DEFAULT_DATA_DIR = Path.home() / "Documents" / "University" / "XII" / "InvExp" / "data"
DEFAULT_OUTPUT_DIR = INVEXP_DIR / "walkTest" / "pose"


class ConfigError(ValueError):
    """Raised when a configuration file contains an unknown or invalid key."""


@dataclass(frozen=True)
class Config:
    """All knobs that can change pose extraction or gait derivation."""

    model: str = "heavy"
    model_dir: Path = POSE_DIR / "models"
    min_pose_detection_confidence: float = 0.5
    min_pose_presence_confidence: float = 0.5
    min_tracking_confidence: float = 0.5
    visibility_threshold: float = 0.5
    smoothing_window: int = 7
    smoothing_order: int = 2
    event_min_distance_s: float = 0.25
    event_prominence_frac: float = 0.015
    event_horizontal_prominence_frac: float = 0.03
    event_ground_tolerance_frac: float = 0.08
    manual_start_frame: int = 1286
    manual_fps: float = 120.0
    px_per_m: float | None = None
    ground_y_px: float | None = None

    def with_overrides(self, **overrides: Any) -> "Config":
        return replace(self, **overrides)

    @property
    def model_path(self) -> Path:
        return self.model_dir / f"pose_landmarker_{self.model}.task"


def load_config(path: Path | None = None, **overrides: Any) -> Config:
    """Load YAML, reject unknown keys, then apply explicit CLI overrides."""
    config = Config()
    if path is not None:
        raw = yaml.safe_load(path.read_text()) or {}
        config = _from_mapping(raw)
    for key, value in overrides.items():
        if value is None:
            continue
        if key not in {field.name for field in fields(Config)}:
            raise ConfigError(f"unknown config override: {key}")
        config = config.with_overrides(**{key: value})
    _validate(config)
    return config


def _from_mapping(raw: dict[str, Any]) -> Config:
    known = {field.name for field in fields(Config)}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(f"unknown config keys: {', '.join(unknown)}")
    values = dict(raw)
    if "model_dir" in values:
        values["model_dir"] = Path(values["model_dir"]).expanduser()
    return Config(**values)


def _validate(config: Config) -> None:
    if config.model not in {"lite", "full", "heavy"}:
        raise ConfigError(f"model must be lite, full or heavy; got {config.model}")
    if not 0.0 <= config.visibility_threshold <= 1.0:
        raise ConfigError("visibility_threshold must be in [0, 1]")
    if config.smoothing_window < 3 or config.smoothing_window % 2 == 0:
        raise ConfigError("smoothing_window must be an odd integer >= 3")
    if config.smoothing_order >= config.smoothing_window:
        raise ConfigError("smoothing_order must be smaller than smoothing_window")
    if config.event_min_distance_s <= 0:
        raise ConfigError("event_min_distance_s must be positive")
    if not 0 < config.event_prominence_frac < 1:
        raise ConfigError("event_prominence_frac must be in (0, 1)")

from __future__ import annotations

import pytest

from invexp_pose.manual import load_manual_annotation, load_tracker_calibration


def test_tracker_world_to_pixel_transform(tmp_path) -> None:
    trk = tmp_path / "clip.trk"
    trk.write_text(
        """<?xml version="1.0"?>
<object>
  <property name="startframe" type="int">1286</property>
  <property name="frame_count" type="int">3126</property>
  <property name="frame_rate" type="int">120</property>
  <property name="xorigin" type="double">137.875</property>
  <property name="yorigin" type="double">733.5</property>
  <property name="xscale" type="double">435.9</property>
  <property name="yscale" type="double">435.9</property>
</object>
"""
    )
    csv = tmp_path / "annotation.csv"
    csv.write_text(
        "#multi:\n"
        ",mass A,,mass B,,\n"
        "t,x,y,x,y,\n"
        "0.0,4.0,-0.5,4.0,-0.5\n"
        "0.008333,4.1,-0.4,4.1,-0.4\n"
    )

    calibration = load_tracker_calibration(trk)
    manual = load_manual_annotation(csv, calibration)

    assert manual.loc[0, "frame"] == 1286
    assert manual.loc[0, "ankle_x_px"] == pytest.approx(137.875 + 435.9 * 4.0)
    assert manual.loc[0, "ankle_y_px"] == pytest.approx(733.5 - 435.9 * -0.5)
    assert manual.loc[1, "frame"] == 1287

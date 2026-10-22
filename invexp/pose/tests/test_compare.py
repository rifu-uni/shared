from __future__ import annotations

import pandas as pd
import pytest

from invexp_pose.compare import match_contacts_to_impacts
from invexp_pose.sync import impact_after_contact


def test_contact_to_impact_matching() -> None:
    contacts = pd.DataFrame(
        {
            "video_id": ["test", "test"],
            "side": ["left", "left"],
            "contact_pts_s": [1.0, 2.0],
            "contact_frame": [120, 240],
        }
    )
    impacts = pd.DataFrame(
        {
            "sensor": ["tibia", "tibia"],
            "impact_index": [10, 11],
            "impact_time_s": [1.05, 2.03],
            "peak_g": [5.0, 6.0],
        }
    )

    matched = match_contacts_to_impacts(
        contacts, impacts, sensor="tibia", max_delay_s=0.2
    )
    assert matched["matched"].tolist() == [True, True]
    assert matched["delay_s"].tolist() == pytest.approx([0.05, 0.03])
    assert matched["impact_peak_g"].tolist() == [5.0, 6.0]


def test_contact_does_not_match_previous_impact() -> None:
    contacts = pd.DataFrame({"contact_pts_s": [2.0]})
    impacts = pd.DataFrame(
        {
            "sensor": ["tibia", "tibia"],
            "impact_index": [0, 1],
            "impact_time_s": [1.95, 2.04],
            "peak_g": [5.0, 6.0],
        }
    )

    matched = impact_after_contact(contacts, impacts, max_delay_s=0.2)
    assert matched.loc[0, "impact_time_s"] == pytest.approx(2.04)

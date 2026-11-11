import numpy as np
import pandas as pd
import rasterio

from riverforecast.config import project_path


def test_bank_positions_and_sign_geometry():
    pos = pd.read_csv(project_path("derived", "measurements", "bank_positions.csv"))
    assert set(pos["side"]) == {"L", "R"}
    assert not pos.duplicated(["year", "transect_id", "side"]).any()
    p23 = pos[pos["year"] == 2023]
    assert len(p23) == 150
    assert p23["valid_bank"].all()
    assert np.allclose(np.hypot(p23["normal_x"], p23["normal_y"]), 1.0, atol=1e-9)
    assert (p23["observation_date"] == "2023-03-25").all()
    for _, g in pos.groupby(["year", "transect_id"]):
        assert len(g) == 2
        assert set(g["side"]) == {"L", "R"}


def test_intervals_cover_all_observations_and_missing_1997_is_two_years():
    intervals = pd.read_csv(project_path("derived", "measurements", "bank_migration_intervals_raw.csv"))
    assert len(intervals) == 4950
    assert len(intervals.groupby(["from_year", "to_year"])) == 33
    pair = intervals[(intervals["from_year"] == 1996) & (intervals["to_year"] == 1998)]
    assert len(pair) == 150
    assert (pair["elapsed_days"] == 730).all()
    assert not set(intervals["from_year"]).intersection({1997})
    assert not set(intervals["to_year"]).intersection({1997})
    assert set(intervals["quality"]).issubset({"good", "flagged", "implausible", "invalid"})


def test_change_map_encoding_matches_interval_table():
    interval = pd.read_csv(project_path("derived", "measurements", "change_intervals.csv"))
    row = interval[(interval["from_year"] == 1989) & (interval["to_year"] == 1990)].iloc[0]
    for name, erosion_col, accretion_col in [
        ("change_1989_1990.tif", "erosion_pixels_raw", "accretion_pixels_raw"),
        ("change_filtered_1989_1990.tif", "erosion_pixels_filtered", "accretion_pixels_filtered"),
    ]:
        with rasterio.open(project_path("derived", "change_maps", name)) as src:
            arr = src.read(1)
            assert src.nodata == 255
        assert set(np.unique(arr)).issubset({-1, 0, 1, 255})
        assert int((arr == 1).sum()) == int(row[erosion_col])
        assert int((arr == -1).sum()) == int(row[accretion_col])

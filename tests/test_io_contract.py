import copy
from pathlib import Path

import numpy as np
import pytest
import rasterio

from riverforecast.config import load_config, project_path
from riverforecast.io import (
    TestDataLockError,
    assert_read_allowed,
    read_mask,
    require_freeze_ready,
    sha256_file,
    verify_frozen_manifest,
)


def test_canonical_grid_and_historical_mask_contract():
    cfg = load_config()
    grid = cfg["canonical_grid"]
    with rasterio.open(project_path(cfg["source_dir"], "MNDWI_Mask_2023.tif")) as src:
        assert src.width == int(grid["width"])
        assert src.height == int(grid["height"])
        assert src.crs.to_string() == grid["crs"]
        assert np.allclose(tuple(src.transform)[:6], tuple(grid["transform"]))
        assert src.descriptions[0].lower() == "water"
        assert src.descriptions[1].lower() == "valid"
    water, valid, info = read_mask(2023, purpose="training")
    assert water.dtype == bool and valid.dtype == bool
    assert water.shape == (int(grid["height"]), int(grid["width"]))
    assert int(water.sum()) > 0
    assert not (water & ~valid).any()
    assert info["aligned"] is True


def test_test_years_are_locked_until_a_valid_freeze():
    frozen = project_path("forecasts", "frozen", "manifest.json")
    if frozen.exists():
        pytest.skip("A frozen forecast exists; the post-freeze test covers evaluation access.")
    with pytest.raises(TestDataLockError):
        assert_read_allowed(2024, purpose="training")
    with pytest.raises(TestDataLockError):
        assert_read_allowed(2024, purpose="evaluation")
    with pytest.raises(TestDataLockError):
        assert_read_allowed(2026, purpose="qa")


def test_frozen_manifest_verifies_all_hashes_after_freeze():
    frozen = project_path("forecasts", "frozen", "manifest.json")
    if not frozen.exists():
        pytest.skip("Forecast is not frozen yet.")
    manifest = require_freeze_ready()
    assert set(manifest["forecast_years"]) == {2024, 2025, 2026}
    assert manifest["training_cutoff_year"] == 2023
    assert manifest["origin_year"] == 2023
    assert manifest["files"]
    assert manifest["inputs"]["code"]
    for name, expected in manifest["inputs"]["code"].items():
        assert sha256_file(project_path("src", "riverforecast", name)) == expected


def test_evaluation_gate_opens_only_after_freeze_and_training_stays_locked():
    frozen = project_path("forecasts", "frozen", "manifest.json")
    if not frozen.exists():
        pytest.skip("Forecast is not frozen yet.")
    assert_read_allowed(2024, purpose="evaluation")
    with pytest.raises(TestDataLockError):
        assert_read_allowed(2024, purpose="training")


def test_frozen_manifest_rejects_changed_code_hash():
    manifest = require_freeze_ready()
    tampered = copy.deepcopy(manifest)
    name = next(iter(tampered["inputs"]["code"]))
    tampered["inputs"]["code"][name] = "0" * 64
    with pytest.raises(TestDataLockError, match="code changed"):
        verify_frozen_manifest(tampered)

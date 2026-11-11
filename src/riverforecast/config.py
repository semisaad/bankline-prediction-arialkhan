from __future__ import annotations

import json
import os
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "pipeline.json"


def load_config(path: Path | None = None) -> dict:
    with open(path or CONFIG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def project_path(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath(*parts)


def ensure_output_dirs() -> None:
    for name in [
        "processed",
        "processed/masks",
        "processed/river",
        "processed/qa",
        "derived",
        "derived/banklines",
        "derived/change_maps",
        "derived/measurements",
        "datasets",
        "validation",
        "validation/figures",
        "models",
        "forecasts",
        "forecasts/frozen",
        "evaluation",
        "evaluation/figures",
        "logs",
        "reports",
    ]:
        project_path(name).mkdir(parents=True, exist_ok=True)


def test_years() -> set[int]:
    return set(load_config()["test_years"])


def is_test_year(year: int) -> bool:
    return int(year) in test_years()


def training_cutoff_year() -> int:
    return int(load_config()["training_cutoff_year"])


def nominal_date(year: int) -> str:
    month_day = load_config()["nominal_observation_end"]
    return f"{int(year):04d}-{month_day}"


def env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).resolve()

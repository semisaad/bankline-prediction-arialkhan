from __future__ import annotations

import ast
import hashlib
import json
import math
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "reports" / "ranking_persistence.json"
PNG_PATH = ROOT / "reports" / "ranking_persistence.png"
PREREG_PATH = ROOT / "reports" / "prereg_ranking.md"

PREREG_SHA256 = "2d0e1567ff811b9dfa7a1eabf8fdd04c7b85e92e08cc85ecf060a12778c17957"
INPUT_HASHES = {
    "derived/measurements/bank_positions.csv": "12e931b90eabe499d950e29299a5d291b1ab4acc46632febc5f6a09582937957",
    "evaluation/observed_bank_positions_2024.csv": "1c36fa950f643b5b8decdde1a736560ada200876e6592587a3f60b05777af4d6",
    "evaluation/observed_bank_positions_2025.csv": "b50477a772bab1c671a4c695bae0c726cfb5d9ec1d2387caee7653d5234d9d67",
    "evaluation/observed_bank_positions_2026.csv": "c0771f0ff53330a8532eca0770c2e086a77d288a2135c5bf22a29a7d9ad9b626",
}
REQUIRED_COLUMNS = {
    "year",
    "transect_id",
    "side",
    "outward_sign",
    "normal_x",
    "normal_y",
    "bank_x",
    "bank_y",
    "curvature_1_m",
    "flags",
    "valid_bank",
    "observation_date",
}

SPLITS = [
    {"id": 1, "a": (1989, 1998), "b": (1999, 2008)},
    {"id": 2, "a": (1994, 2003), "b": (2004, 2013)},
    {"id": 3, "a": (1999, 2008), "b": (2009, 2018)},
    {"id": 4, "a": (2004, 2013), "b": (2014, 2023)},
    {"id": 5, "a": (2007, 2016), "b": (2017, 2026)},
]

TOP_FRACTION = 0.20
MIN_LIFT = 1.5
PASS_SPLITS = 4
BOOTSTRAP_REPLICATES = 1000
PERMUTATIONS = 1000
STRETCH_BLOCK_SIZE = 5
SEED = 42


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_flags(value: object) -> list[str]:
    if isinstance(value, list):
        return value
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    parsed = ast.literal_eval(str(value))
    if not isinstance(parsed, list):
        raise ValueError(f"flags is not a list: {value!r}")
    return [str(item) for item in parsed]


def finite_number(value: object) -> bool:
    return isinstance(value, (int, float, np.integer, np.floating)) and math.isfinite(float(value))


def load_data() -> tuple[pd.DataFrame, dict[str, str]]:
    actual_prereg = sha256_file(PREREG_PATH)
    if actual_prereg != PREREG_SHA256:
        raise RuntimeError(f"pre-registration hash changed: {actual_prereg}")

    frames = []
    hashes = {}
    for relative, expected in INPUT_HASHES.items():
        path = ROOT / relative
        actual = sha256_file(path)
        if actual != expected:
            raise RuntimeError(f"input hash changed for {relative}: {actual}")
        hashes[relative] = actual
        frame = pd.read_csv(path)
        missing = REQUIRED_COLUMNS - set(frame.columns)
        if missing:
            raise RuntimeError(f"{relative} is missing columns: {sorted(missing)}")
        frames.append(frame)

    data = pd.concat(frames, ignore_index=True)
    keys = ["year", "side", "transect_id"]
    if data.duplicated(keys).any():
        raise RuntimeError("duplicate year/side/transect rows")
    if 1997 in set(data["year"].astype(int)):
        raise RuntimeError("unexpected 1997 bank positions")

    data["flags_list"] = data["flags"].map(parse_flags)
    data["observation_date"] = pd.to_datetime(data["observation_date"], errors="coerce")
    data["row_usable"] = (
        data["valid_bank"].astype(bool)
        & data["flags_list"].map(len).eq(0)
        & data["year"].ne(1997)
        & data[["bank_x", "bank_y", "normal_x", "normal_y", "outward_sign"]].apply(
            np.isfinite
        ).all(axis=1)
        & data["observation_date"].notna()
    )
    return data, hashes


def check_fixed_geometry(data: pd.DataFrame) -> None:
    for (side, transect_id), group in data.groupby(["side", "transect_id"], sort=False):
        geometry = group[["normal_x", "normal_y", "outward_sign"]].to_numpy(dtype=float)
        if not np.allclose(geometry, geometry[0], rtol=0.0, atol=1e-10):
            raise RuntimeError(f"geometry changes across years for {side} transect {transect_id}")


def make_stretches() -> list[dict[str, object]]:
    stretches = []
    order = 0
    for side in ("L", "R"):
        for start in range(1, 76, 3):
            stretches.append(
                {
                    "stretch_id": f"{side}_{start:02d}_{start + 2:02d}",
                    "side": side,
                    "start": start,
                    "end": start + 2,
                    "transect_ids": [start, start + 1, start + 2],
                    "order": order,
                }
            )
            order += 1
    tie_order = np.random.default_rng(SEED).permutation(len(stretches))
    for index, stretch in enumerate(stretches):
        stretch["tie_rank"] = int(tie_order[index])
    return stretches


def make_transects() -> list[dict[str, object]]:
    transects = []
    order = 0
    for side in ("L", "R"):
        for transect_id in range(1, 76):
            transects.append(
                {
                    "transect_id": f"{side}_{transect_id:02d}",
                    "side": side,
                    "number": transect_id,
                    "order": order,
                }
            )
            order += 1
    tie_order = np.random.default_rng(SEED).permutation(len(transects))
    for index, transect in enumerate(transects):
        transect["tie_rank"] = int(tie_order[index])
    return transects


def transect_activity_table(data: pd.DataFrame) -> dict[tuple[str, int], dict[int, dict[str, float | None]]]:
    lookup = {
        (int(row.year), str(row.side), int(row.transect_id)): row
        for row in data.itertuples(index=False)
    }
    table: dict[tuple[str, int], dict[int, dict[str, float | None]]] = {}
    for side in ("L", "R"):
        for transect_id in range(1, 76):
            key = (side, transect_id)
            table[key] = {}
            for split in SPLITS:
                values: dict[str, float | None] = {}
                for period_name, (start_year, end_year) in (("A", split["a"]), ("B", split["b"])):
                    start_row = lookup.get((start_year, side, transect_id))
                    end_row = lookup.get((end_year, side, transect_id))
                    activity = None
                    if (
                        start_row is not None
                        and end_row is not None
                        and bool(start_row.row_usable)
                        and bool(end_row.row_usable)
                    ):
                        elapsed = (
                            end_row.observation_date - start_row.observation_date
                        ).total_seconds() / (365.25 * 24 * 60 * 60)
                        if elapsed > 0:
                            displacement = (
                                (float(end_row.bank_x) - float(start_row.bank_x))
                                * float(start_row.normal_x)
                                + (float(end_row.bank_y) - float(start_row.bank_y))
                                * float(start_row.normal_y)
                            )
                            activity = float(displacement * float(start_row.outward_sign) / elapsed)
                    values[period_name] = activity
                table[key][int(split["id"])] = values
    return table


def stretch_period_table(
    transect_table: dict[tuple[str, int], dict[int, dict[str, float | None]]],
    stretches: list[dict[str, object]],
    rng: np.random.Generator,
) -> dict[str, dict[int, dict[str, dict[str, object]]]]:
    result: dict[str, dict[int, dict[str, dict[str, object]]]] = {}
    for stretch in stretches:
        stretch_id = str(stretch["stretch_id"])
        side = str(stretch["side"])
        ids = list(stretch["transect_ids"])
        result[stretch_id] = {}
        for split in SPLITS:
            split_id = int(split["id"])
            result[stretch_id][split_id] = {}
            for period_name in ("A", "B"):
                values = [
                    transect_table[(side, transect_id)][split_id][period_name]
                    for transect_id in ids
                ]
                usable = [float(value) for value in values if value is not None]
                activity = float(np.mean(usable)) if usable else None
                lower = upper = None
                includes_zero = None
                if len(usable) >= 2:
                    draws = rng.choice(
                        np.asarray(usable, dtype=float),
                        size=(BOOTSTRAP_REPLICATES, len(usable)),
                        replace=True,
                    ).mean(axis=1)
                    lower, upper = (float(value) for value in np.percentile(draws, [5, 95]))
                    includes_zero = bool(lower <= 0.0 <= upper)
                result[stretch_id][split_id][period_name] = {
                    "activity_m_per_yr": activity,
                    "transect_values_m_per_yr": usable,
                    "n_transects": len(usable),
                    "interval_90_m_per_yr": [lower, upper] if lower is not None else None,
                    "interval_includes_zero": includes_zero,
                }
    return result


def curvature_table(
    data: pd.DataFrame,
    stretches: list[dict[str, object]],
) -> dict[str, dict[int, float | None]]:
    lookup = {
        (int(row.year), str(row.side), int(row.transect_id)): row
        for row in data.itertuples(index=False)
    }
    result: dict[str, dict[int, float | None]] = {}
    for stretch in stretches:
        stretch_id = str(stretch["stretch_id"])
        side = str(stretch["side"])
        ids = list(stretch["transect_ids"])
        result[stretch_id] = {}
        for split in SPLITS:
            end_year = int(split["a"][1])
            values = []
            for transect_id in ids:
                row = lookup.get((end_year, side, transect_id))
                if row is not None and finite_number(getattr(row, "curvature_1_m")):
                    values.append(abs(float(getattr(row, "curvature_1_m"))))
            result[stretch_id][int(split["id"])] = float(np.mean(values)) if values else None
    return result


def top_positions(values: np.ndarray, tie_ranks: np.ndarray, k: int) -> np.ndarray:
    if k <= 0:
        return np.empty(0, dtype=int)
    order = np.lexsort((np.arange(len(values)), tie_ranks, -values))
    return order[:k]


def rank_metrics(
    ranker_values: np.ndarray,
    later_values: np.ndarray,
    tie_ranks: np.ndarray,
) -> dict[str, object]:
    n = int(len(ranker_values))
    if n == 0:
        return {
            "n": 0,
            "k": 0,
            "spearman": None,
            "top_overlap": None,
            "lift": None,
            "top_ranker_positions": [],
            "top_later_positions": [],
        }
    k = max(1, int(math.ceil(TOP_FRACTION * n)))
    top_ranker = top_positions(ranker_values, tie_ranks, k)
    top_later = top_positions(later_values, tie_ranks, k)
    overlap_count = len(set(int(value) for value in top_ranker) & set(int(value) for value in top_later))
    overlap = overlap_count / k
    lift = overlap / TOP_FRACTION
    if n >= 2 and np.std(ranker_values) > 0 and np.std(later_values) > 0:
        rho = spearmanr(ranker_values, later_values).statistic
        rho_value = float(rho) if finite_number(rho) else None
    else:
        rho_value = None
    return {
        "n": n,
        "k": k,
        "spearman": rho_value,
        "top_overlap": float(overlap),
        "lift": float(lift),
        "overlap_count": int(overlap_count),
        "top_ranker_positions": [int(value) for value in top_ranker],
        "top_later_positions": [int(value) for value in top_later],
    }


def percentile_interval(values: list[float], low: float = 5.0, high: float = 95.0) -> list[float] | None:
    clean = np.asarray([value for value in values if finite_number(value)], dtype=float)
    if clean.size == 0:
        return None
    lower, upper = np.percentile(clean, [low, high])
    return [float(lower), float(upper)]


def bootstrap_metrics(
    all_values: np.ndarray,
    later_values: np.ndarray | None,
    tie_ranks: np.ndarray,
    blocks: list[list[int]],
    rng: np.random.Generator,
) -> dict[str, object]:
    rhos = []
    lifts = []
    for _ in range(BOOTSTRAP_REPLICATES):
        block_indices = rng.integers(0, len(blocks), size=len(blocks))
        positions = np.concatenate([blocks[int(block)] for block in block_indices])
        mask = np.isfinite(all_values[positions])
        if later_values is not None:
            mask &= np.isfinite(later_values[positions])
        positions = positions[mask]
        if len(positions) < 4:
            continue
        ranker = all_values[positions]
        later = later_values[positions] if later_values is not None else None
        metrics = rank_metrics(ranker, later, tie_ranks[positions])
        if metrics["spearman"] is not None:
            rhos.append(float(metrics["spearman"]))
        lifts.append(float(metrics["lift"]))
    return {
        "replicates_requested": BOOTSTRAP_REPLICATES,
        "replicates_used": len(lifts),
        "spearman_ci_90": percentile_interval(rhos),
        "lift_ci_90": percentile_interval(lifts),
    }


def random_bands(
    earlier_values: np.ndarray,
    later_values: np.ndarray,
    tie_ranks: np.ndarray,
    rng: np.random.Generator,
) -> dict[str, object]:
    if len(earlier_values) == 0:
        return {
            "permutations": PERMUTATIONS,
            "spearman_band_90": None,
            "lift_band_90": None,
            "lift_mean": None,
            "spearman_mean": None,
        }
    rhos = []
    lifts = []
    for _ in range(PERMUTATIONS):
        permuted = rng.permutation(earlier_values)
        metrics = rank_metrics(permuted, later_values, tie_ranks)
        if metrics["spearman"] is not None:
            rhos.append(float(metrics["spearman"]))
        lifts.append(float(metrics["lift"]))
    spearman_band = percentile_interval(rhos)
    lift_band = percentile_interval(lifts)
    return {
        "permutations": PERMUTATIONS,
        "spearman_band_90": spearman_band,
        "lift_band_90": lift_band,
        "lift_mean": float(np.mean(lifts)) if lifts else None,
        "spearman_mean": float(np.mean(rhos)) if rhos else None,
    }


def interval_share(
    stretches: list[dict[str, object]],
    stretch_table: dict[str, dict[int, dict[str, dict[str, object]]]],
    split_id: int,
    period_name: str,
) -> dict[str, object]:
    with_activity = 0
    defined = 0
    includes = 0
    for stretch in stretches:
        record = stretch_table[str(stretch["stretch_id"])][split_id][period_name]
        if record["activity_m_per_yr"] is not None:
            with_activity += 1
        if record["interval_includes_zero"] is not None:
            defined += 1
            includes += int(bool(record["interval_includes_zero"]))
    return {
        "n_stretches_with_activity": with_activity,
        "n_stretches_with_interval": defined,
        "n_intervals_including_zero": includes,
        "share_intervals_including_zero": float(includes / defined) if defined else None,
    }


def make_jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): make_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [make_jsonable(item) for item in value]
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if not math.isfinite(float(value)):
            return None
        return float(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    return value


def build_result(
    data: pd.DataFrame,
    hashes: dict[str, str],
    stretches: list[dict[str, object]],
    transects: list[dict[str, object]],
    transect_table: dict[tuple[str, int], dict[int, dict[str, float | None]]],
    stretch_table: dict[str, dict[int, dict[str, dict[str, object]]]],
    curvatures: dict[str, dict[int, float | None]],
) -> dict[str, object]:
    blocks = [
        list(range(index, index + STRETCH_BLOCK_SIZE))
        for index in range(0, len(stretches), STRETCH_BLOCK_SIZE)
    ]
    if any(len(block) != STRETCH_BLOCK_SIZE for block in blocks):
        raise RuntimeError("stretch block construction failed")

    stretch_ids = [str(stretch["stretch_id"]) for stretch in stretches]
    stretch_ties = np.asarray([int(stretch["tie_rank"]) for stretch in stretches])
    split_results = []
    rng_bootstrap_a = np.random.default_rng(SEED)
    rng_bootstrap_curvature = np.random.default_rng(SEED)
    rng_random = np.random.default_rng(SEED)

    for split in SPLITS:
        split_id = int(split["id"])
        common = [
            stretch_id
            for stretch_id in stretch_ids
            if stretch_table[stretch_id][split_id]["A"]["activity_m_per_yr"] is not None
            and stretch_table[stretch_id][split_id]["B"]["activity_m_per_yr"] is not None
        ]
        common_positions = [stretch_ids.index(stretch_id) for stretch_id in common]
        earlier = np.asarray(
            [float(stretch_table[stretch_id][split_id]["A"]["activity_m_per_yr"]) for stretch_id in common],
            dtype=float,
        )
        later = np.asarray(
            [float(stretch_table[stretch_id][split_id]["B"]["activity_m_per_yr"]) for stretch_id in common],
            dtype=float,
        )
        ties = stretch_ties[common_positions]
        primary = rank_metrics(earlier, later, ties)
        primary["top_ranker_ids"] = [common[int(position)] for position in primary["top_ranker_positions"]]
        primary["top_later_ids"] = [common[int(position)] for position in primary["top_later_positions"]]
        primary.pop("top_ranker_positions")
        primary.pop("top_later_positions")

        all_earlier = np.asarray(
            [
                stretch_table[stretch_id][split_id]["A"]["activity_m_per_yr"]
                if stretch_table[stretch_id][split_id]["A"]["activity_m_per_yr"] is not None
                else np.nan
                for stretch_id in stretch_ids
            ],
            dtype=float,
        )
        all_later = np.asarray(
            [
                stretch_table[stretch_id][split_id]["B"]["activity_m_per_yr"]
                if stretch_table[stretch_id][split_id]["B"]["activity_m_per_yr"] is not None
                else np.nan
                for stretch_id in stretch_ids
            ],
            dtype=float,
        )
        primary_bootstrap = bootstrap_metrics(
            all_earlier,
            all_later,
            stretch_ties,
            blocks,
            rng_bootstrap_a,
        )
        random_result = random_bands(earlier, later, ties, rng_random)

        curvature_common = [
            stretch_id
            for stretch_id in common
            if curvatures[stretch_id][split_id] is not None
        ]
        curvature_positions = [stretch_ids.index(stretch_id) for stretch_id in curvature_common]
        curvature_values = np.asarray(
            [float(curvatures[stretch_id][split_id]) for stretch_id in curvature_common],
            dtype=float,
        )
        curvature_later = np.asarray(
            [
                float(stretch_table[stretch_id][split_id]["B"]["activity_m_per_yr"])
                for stretch_id in curvature_common
            ],
            dtype=float,
        )
        curvature_ties = stretch_ties[curvature_positions]
        curvature_metrics = rank_metrics(curvature_values, curvature_later, curvature_ties)
        curvature_metrics["top_ranker_ids"] = [
            curvature_common[int(position)] for position in curvature_metrics["top_ranker_positions"]
        ]
        curvature_metrics["top_later_ids"] = [
            curvature_common[int(position)] for position in curvature_metrics["top_later_positions"]
        ]
        curvature_metrics.pop("top_ranker_positions")
        curvature_metrics.pop("top_later_positions")
        all_curvature = np.asarray(
            [
                curvatures[stretch_id][split_id]
                if curvatures[stretch_id][split_id] is not None
                else np.nan
                for stretch_id in stretch_ids
            ],
            dtype=float,
        )
        all_curvature = np.where(np.isfinite(all_earlier), all_curvature, np.nan)
        curvature_bootstrap = bootstrap_metrics(
            all_curvature,
            all_later,
            stretch_ties,
            blocks,
            rng_bootstrap_curvature,
        )
        curvature_metrics["bootstrap"] = curvature_bootstrap

        split_results.append(
            {
                "split": split_id,
                "period_a": f"{split['a'][0]}-{split['a'][1]}",
                "period_b": f"{split['b'][0]}-{split['b'][1]}",
                "n_common_stretches": len(common),
                "common_stretch_ids": common,
                "primary_a_activity": primary,
                "primary_bootstrap": primary_bootstrap,
                "random": random_result,
                "curvature": curvature_metrics,
                "zero_interval_share": {
                    "period_a": interval_share(stretches, stretch_table, split_id, "A"),
                    "period_b": interval_share(stretches, stretch_table, split_id, "B"),
                },
            }
        )

    transect_split_results = []
    transect_ids = [str(transect["transect_id"]) for transect in transects]
    transect_ties_all = np.asarray([int(transect["tie_rank"]) for transect in transects])
    for split in SPLITS:
        split_id = int(split["id"])
        common = []
        for transect in transects:
            key = (str(transect["side"]), int(transect["number"]))
            record = transect_table[key][split_id]
            if record["A"] is not None and record["B"] is not None:
                common.append(str(transect["transect_id"]))
        common_positions = [transect_ids.index(transect_id) for transect_id in common]
        earlier = np.asarray(
            [
                float(transect_table[(str(transects[index]["side"]), int(transects[index]["number"]))][split_id]["A"])
                for index in common_positions
            ],
            dtype=float,
        )
        later = np.asarray(
            [
                float(transect_table[(str(transects[index]["side"]), int(transects[index]["number"]))][split_id]["B"])
                for index in common_positions
            ],
            dtype=float,
        )
        ties = transect_ties_all[common_positions]
        metrics = rank_metrics(earlier, later, ties)
        metrics["top_ranker_ids"] = [common[int(position)] for position in metrics["top_ranker_positions"]]
        metrics["top_later_ids"] = [common[int(position)] for position in metrics["top_later_positions"]]
        metrics.pop("top_ranker_positions")
        metrics.pop("top_later_positions")
        transect_split_results.append(
            {
                "split": split_id,
                "period_a": f"{split['a'][0]}-{split['a'][1]}",
                "period_b": f"{split['b'][0]}-{split['b'][1]}",
                "n_common_transects": len(common),
                "metrics": metrics,
            }
        )

    lift_passes = sum(
        1
        for split in split_results
        if split["primary_a_activity"]["lift"] is not None
        and float(split["primary_a_activity"]["lift"]) >= MIN_LIFT
    )
    spearman_passes = sum(
        1
        for split in split_results
        if split["primary_bootstrap"]["spearman_ci_90"] is not None
        and float(split["primary_bootstrap"]["spearman_ci_90"][0]) > 0.0
    )
    success = bool(lift_passes >= PASS_SPLITS and spearman_passes >= PASS_SPLITS)

    activity_records: dict[str, dict[str, dict[str, list[dict[str, object]]]]] = {}
    for split in SPLITS:
        split_key = str(split["id"])
        activity_records[split_key] = {"A": [], "B": []}
        for period_name in ("A", "B"):
            for stretch in stretches:
                stretch_id = str(stretch["stretch_id"])
                record = stretch_table[stretch_id][int(split["id"])][period_name]
                activity_records[split_key][period_name].append(
                    {
                        "stretch_id": stretch_id,
                        "side": str(stretch["side"]),
                        "start_transect": int(stretch["start"]),
                        "end_transect": int(stretch["end"]),
                        **record,
                    }
                )

    try:
        prereg_commit = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        prereg_commit = None

    return {
        "title": "Ranking persistence of active bank stretches",
        "date": "2026-10-21",
        "prereg": {
            "path": "reports/prereg_ranking.md",
            "sha256": sha256_file(PREREG_PATH),
            "commit": prereg_commit,
        },
        "inputs": {
            "paths_and_sha256": hashes,
            "n_rows": int(len(data)),
            "years": [int(data["year"].min()), int(data["year"].max())],
            "n_transects": len(transects),
            "n_stretches": len(stretches),
        },
        "config": {
            "splits": [
                {
                    "split": int(split["id"]),
                    "period_a": [int(split["a"][0]), int(split["a"][1])],
                    "period_b": [int(split["b"][0]), int(split["b"][1])],
                }
                for split in SPLITS
            ],
            "top_fraction": TOP_FRACTION,
            "min_lift": MIN_LIFT,
            "pass_splits": PASS_SPLITS,
            "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            "permutations": PERMUTATIONS,
            "stretch_block_size": STRETCH_BLOCK_SIZE,
            "seed": SEED,
            "stretch_order": stretch_ids,
            "clean_rule": "valid_bank true, flags empty, year != 1997, finite geometry and date",
            "activity_unit": "metres per year, positive outward",
            "prior_exposure": "second look; 2025 and 2026 were already examined",
        },
        "stretch_activity": activity_records,
        "splits": split_results,
        "transect_secondary": {
            "note": "sensitivity only; no bootstrap, random band or success role",
            "splits": transect_split_results,
        },
        "success": {
            "success": success,
            "lift_passes": int(lift_passes),
            "spearman_passes": int(spearman_passes),
            "rule": "lift >= 1.5 in at least 4 of 5 splits and Spearman 90% lower bound > 0 in at least 4 of 5 splits",
        },
        "limitations": [
            "The five split pairs overlap and are not independent evidence.",
            "This is a second look; 2025 and 2026 outcomes were already examined.",
            "A stretch can be represented by one or two transects when some endpoints are flagged.",
            "No missing endpoint, flagged observation or missing year is interpolated.",
            "The per-stretch zero check is a within-stretch transect bootstrap, not the split-level spatial block bootstrap.",
            "The result is descriptive for this reach and is not a prospective forecast.",
        ],
    }


def make_figure(result: dict[str, object]) -> None:
    splits = result["splits"]
    stretch_activity = result["stretch_activity"]
    fig = plt.figure(figsize=(16, 9))
    grid = fig.add_gridspec(2, 5, height_ratios=[1.0, 0.9], hspace=0.38, wspace=0.32)

    for index, split in enumerate(splits):
        axis = fig.add_subplot(grid[0, index])
        split_key = str(split["split"])
        common = set(split["common_stretch_ids"])
        records_a = {
            record["stretch_id"]: record["activity_m_per_yr"]
            for record in stretch_activity[split_key]["A"]
            if record["stretch_id"] in common
        }
        records_b = {
            record["stretch_id"]: record["activity_m_per_yr"]
            for record in stretch_activity[split_key]["B"]
            if record["stretch_id"] in common
        }
        earlier = np.asarray([records_a[stretch_id] for stretch_id in split["common_stretch_ids"]], dtype=float)
        later = np.asarray([records_b[stretch_id] for stretch_id in split["common_stretch_ids"]], dtype=float)
        axis.axhline(0.0, color="#999999", linewidth=0.8)
        axis.axvline(0.0, color="#999999", linewidth=0.8)
        axis.scatter(earlier, later, s=24, alpha=0.72, color="#1f6f8b", edgecolor="white", linewidth=0.4)
        axis.set_title(
            f"Split {split['split']}: {split['period_a']} to {split['period_b']}\n"
            f"A vs B",
            fontsize=9.5,
            loc="left",
        )
        axis.set_xlabel("Earlier activity (m/yr)", fontsize=8)
        axis.set_ylabel("Later activity (m/yr)", fontsize=8)
        axis.tick_params(labelsize=7)
        rho = split["primary_a_activity"]["spearman"]
        rho_ci = split["primary_bootstrap"]["spearman_ci_90"]
        lift = split["primary_a_activity"]["lift"]
        lift_ci = split["primary_bootstrap"]["lift_ci_90"]
        rho_text = "undefined" if rho is None else f"{float(rho):.3f}"
        if rho_ci is None:
            rho_ci_text = "undefined"
        else:
            rho_ci_text = f"[{float(rho_ci[0]):.3f}, {float(rho_ci[1]):.3f}]"
        lift_text = "undefined" if lift is None else f"{float(lift):.2f}"
        if lift_ci is None:
            lift_ci_text = "undefined"
        else:
            lift_ci_text = f"[{float(lift_ci[0]):.2f}, {float(lift_ci[1]):.2f}]"
        axis.text(
            0.02,
            0.02,
            f"n={split['n_common_stretches']}\nrho={rho_text} {rho_ci_text}\nlift={lift_text} {lift_ci_text}",
            transform=axis.transAxes,
            fontsize=6.7,
            va="bottom",
            ha="left",
            bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none", "pad": 1.5},
        )

    axis = fig.add_subplot(grid[1, :])
    xs = np.arange(1, len(splits) + 1)
    random_low = []
    random_high = []
    a_lift = []
    a_low = []
    a_high = []
    curvature_lift = []
    curvature_low = []
    curvature_high = []
    for split in splits:
        random_band = split["random"]["lift_band_90"]
        random_low.append(np.nan if random_band is None else random_band[0])
        random_high.append(np.nan if random_band is None else random_band[1])
        lift = split["primary_a_activity"]["lift"]
        lift_ci = split["primary_bootstrap"]["lift_ci_90"]
        a_lift.append(lift)
        a_low.append(np.nan if lift_ci is None else lift_ci[0])
        a_high.append(np.nan if lift_ci is None else lift_ci[1])
        curvature_lift.append(split["curvature"]["lift"])
        curvature_ci = split["curvature"]["bootstrap"]["lift_ci_90"]
        curvature_low.append(np.nan if curvature_ci is None else curvature_ci[0])
        curvature_high.append(np.nan if curvature_ci is None else curvature_ci[1])

    random_low = np.asarray(random_low, dtype=float)
    random_high = np.asarray(random_high, dtype=float)
    a_lift = np.asarray([np.nan if value is None else value for value in a_lift], dtype=float)
    a_low = np.asarray(a_low, dtype=float)
    a_high = np.asarray(a_high, dtype=float)
    curvature_lift = np.asarray(
        [np.nan if value is None else value for value in curvature_lift], dtype=float
    )
    curvature_low = np.asarray(curvature_low, dtype=float)
    curvature_high = np.asarray(curvature_high, dtype=float)
    axis.fill_between(
        xs,
        random_low,
        random_high,
        color="#b8b8b8",
        alpha=0.42,
        label="random ranking 90% band",
    )
    axis.axhline(1.0, color="#777777", linewidth=0.9, linestyle=":")
    axis.axhline(MIN_LIFT, color="#b23a48", linewidth=1.0, linestyle="--", label=f"pass threshold {MIN_LIFT:.1f}")
    valid_a = np.isfinite(a_lift)
    axis.errorbar(
        xs[valid_a],
        a_lift[valid_a],
        yerr=[
            a_lift[valid_a] - a_low[valid_a],
            a_high[valid_a] - a_lift[valid_a],
        ],
        fmt="o",
        color="#1f6f8b",
        ecolor="#1f6f8b",
        elinewidth=1.0,
        capsize=3,
        label="earlier activity lift",
    )
    valid_curvature = np.isfinite(curvature_lift)
    axis.errorbar(
        xs[valid_curvature],
        curvature_lift[valid_curvature],
        yerr=[
            curvature_lift[valid_curvature] - curvature_low[valid_curvature],
            curvature_high[valid_curvature] - curvature_lift[valid_curvature],
        ],
        fmt="^",
        color="#c47b20",
        ecolor="#c47b20",
        elinewidth=1.0,
        capsize=3,
        label="curvature lift",
    )
    axis.set_xticks(xs)
    axis.set_xticklabels(
        [f"{split['split']}\n{split['period_a']}\nto {split['period_b']}" for split in splits],
        fontsize=8,
    )
    axis.set_ylabel("Top-20% lift", fontsize=9)
    axis.set_xlim(0.65, len(splits) + 0.35)
    axis.tick_params(labelsize=8)
    axis.grid(axis="y", color="#dddddd", linewidth=0.6)
    axis.legend(fontsize=8, loc="upper right", frameon=True)
    axis.set_title(
        "Lift by split; overlapping splits are not independent",
        fontsize=10,
        loc="left",
    )

    fig.suptitle(
        "Rank persistence of 1 km bank stretches, 1989-2026",
        fontsize=13,
        x=0.06,
        ha="left",
    )
    fig.savefig(PNG_PATH, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    data, hashes = load_data()
    check_fixed_geometry(data)
    stretches = make_stretches()
    transects = make_transects()
    transect_table = transect_activity_table(data)
    stretch_table = stretch_period_table(transect_table, stretches, np.random.default_rng(SEED))
    curvatures = curvature_table(data, stretches)
    result = build_result(
        data,
        hashes,
        stretches,
        transects,
        transect_table,
        stretch_table,
        curvatures,
    )
    if all(split["n_common_stretches"] == 0 for split in result["splits"]):
        raise RuntimeError("every split has zero common stretches")
    JSON_PATH.write_text(
        json.dumps(make_jsonable(result), indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    make_figure(result)
    for split in result["splits"]:
        print(
            f"split {split['split']} {split['period_a']}->{split['period_b']}: "
            f"n={split['n_common_stretches']} "
            f"rho={split['primary_a_activity']['spearman']} "
            f"rho_ci={split['primary_bootstrap']['spearman_ci_90']} "
            f"lift={split['primary_a_activity']['lift']} "
            f"lift_ci={split['primary_bootstrap']['lift_ci_90']}"
        )
    print(json.dumps(result["success"], indent=2))
    print(f"wrote {JSON_PATH}")
    print(f"wrote {PNG_PATH}")


if __name__ == "__main__":
    main()

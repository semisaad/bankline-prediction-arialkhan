from __future__ import annotations

import csv
import json
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "derived" / "external"
REACH = (23.24884, 90.16800)
PADMA = (23.47500, 90.12500)
FLOW_START = "1997-01-01"
FLOW_END = "2026-10-20"
RAIN_START = "1989-01-01"
RAIN_END = "2026-10-20"


def fetch(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=180) as response:
        if response.status != 200:
            raise RuntimeError(f"{response.status} for {url}")
        return json.load(response)


def write_daily(path: Path, daily: dict, fields: list[str]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", *fields])
        columns = [daily[name] for name in fields]
        for index, date in enumerate(daily["time"]):
            writer.writerow([date, *[column[index] for column in columns]])


def fetch_flow(name: str, point: tuple[float, float]) -> dict:
    params = urllib.parse.urlencode({
        "latitude": point[0],
        "longitude": point[1],
        "daily": "river_discharge",
        "start_date": FLOW_START,
        "end_date": FLOW_END,
        "timezone": "UTC",
    })
    data = fetch(f"https://flood-api.open-meteo.com/v1/flood?{params}")
    write_daily(OUT / f"{name}_discharge_daily.csv", data["daily"], ["river_discharge"])
    return {
        "requested_point": point,
        "returned_grid_point": [data["latitude"], data["longitude"]],
        "units": data["daily_units"],
        "source": "Open-Meteo Flood API (GloFAS river discharge)",
        "url": f"https://flood-api.open-meteo.com/v1/flood?{params}",
    }


def fetch_rain(name: str, point: tuple[float, float]) -> dict:
    params = urllib.parse.urlencode({
        "latitude": point[0],
        "longitude": point[1],
        "start_date": RAIN_START,
        "end_date": RAIN_END,
        "daily": "precipitation_sum,et0_fao_evapotranspiration,soil_moisture_0_to_7cm_mean",
        "timezone": "UTC",
    })
    data = fetch(f"https://archive-api.open-meteo.com/v1/archive?{params}")
    fields = ["precipitation_sum", "et0_fao_evapotranspiration", "soil_moisture_0_to_7cm_mean"]
    write_daily(OUT / f"{name}_daily.csv", data["daily"], fields)
    return {
        "requested_point": point,
        "returned_grid_point": [data["latitude"], data["longitude"]],
        "units": data["daily_units"],
        "source": "Open-Meteo Archive API (ERA5-Land)",
        "url": f"https://archive-api.open-meteo.com/v1/archive?{params}",
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    metadata = {
        "reach_point": REACH,
        "padma_point": PADMA,
        "flow_period": [FLOW_START, FLOW_END],
        "rain_period": [RAIN_START, RAIN_END],
        "flow": {
            "local": fetch_flow("local", REACH),
            "padma": fetch_flow("padma", PADMA),
        },
        "rain": {
            "reach": fetch_rain("rainfall_reach", REACH),
            "padma": fetch_rain("rainfall_upstream", PADMA),
        },
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()

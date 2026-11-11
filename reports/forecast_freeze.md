# Forecast freeze manifest

- Frozen UTC: 2026-10-20T17:25:02.413118+00:00
- Origin year: 2023
- Forecast years: 2024, 2025, 2026
- Model: Random forest
- Training cutoff: 2023
- Segments per year: 150

## Frozen files

| File | SHA256 | Size (bytes) |
|---|---|---:|
| `bank_points_2024.geojson` | `8691c0ca60f5ce09565666b819c539704dae12a41230501031efc9190bd609b4` | 55567 |
| `bank_points_2025.geojson` | `e72d3641c7b2ed612c5a7796490f1aaef3363effc73bf72601d3c23c05201d3d` | 55577 |
| `bank_points_2026.geojson` | `dc6544b8f3ef99741d54cd7076fa98028ea7e7a00ad0e49f5a85349d39f99178` | 55534 |
| `banklines_2024.geojson` | `d2c14782a764f64b3f905e923c27d1a80a3d2177b3d7bd94e8467b8c91a0f224` | 21063 |
| `banklines_2025.geojson` | `b532aa51a7c84b42baf860b8dc55a925e2ba3db0de0546be06351dc08d9904ff` | 21086 |
| `banklines_2026.geojson` | `d9516788c7d4cabc0f6c290ab1ae3f5a47bd718709473d49f49c2fa21b61b9ed` | 21047 |
| `forecast_summary.json` | `98bff08eb28eddff4cf2c3b301c837397510c663e93f0e87573ad12fbe8c40c6` | 6295 |
| `model_metadata_used.json` | `47e377fb5eec8a48c6d12c84cd84de083f17a4104e39fd18d343d41be9b089a4` | 5313 |
| `observed_banklines_2023.geojson` | `0716004b53afa68fc753707ecf5f2bb9c9a10c8921d731dbda56b1085e6da5ee` | 21039 |
| `segments_2024.csv` | `24190e923bc91c878562d0df5e1212d4347891cce538eeb5d9da0d6e5c10276c` | 26813 |
| `segments_2024.geojson` | `ec53bd921cb65a7204346da1b90c499a0b387784a9da9709d550d0687a6b9cce` | 121793 |
| `segments_2025.csv` | `27ca9d66a4eab5b77a4061528d024d8ac729e457c87d13e375e2202d9c8fb595` | 26810 |
| `segments_2025.geojson` | `cb1628b8f2a1bd8ff495a1d4310cba0ebee8565dfb28c90b1d6a9da4bdf1bb59` | 121861 |
| `segments_2026.csv` | `24e9e28cf545aa43ef04cf4d384305a212466ee7103a6f783a02fa7e2e18c4f3` | 26726 |
| `segments_2026.geojson` | `4f4aaa4b07ee562dc12a6c16b9dacd73011c3e4df136f04111cf49c8a16a010f` | 121809 |

## Input hashes

| Input | SHA256 |
|---|---|
| `config_sha256` | `7d65b4b0597f326d1b7fea12edef4b305cac493cfacd9b27e7f56788e0ac8c37` |
| `dataset_sha256` | `ab2ce7a529a0d237ad34bf01523051a638e059dc58408565c0d8eef83380f060` |
| `forecast_features_sha256` | `ffa6e5e3de2779f20a68359e83661143809dc4a91a20ebce9e91ffb6ab5ee568` |
| `model_artifact_sha256` | `84714efae3ee38a6d89277799fad5f87c5bb31e6e884d8124462dafb97eceaad` |
| `model_metadata_sha256` | `47e377fb5eec8a48c6d12c84cd84de083f17a4104e39fd18d343d41be9b089a4` |
| `code/forecast.py` | `55b84b2626a6492d70d5bf860183a229dc837d329749889a08c2a053f927d6cc` |
| `code/models.py` | `1cac359d234b02abf5eb2835b9b7909f390834fbd48ffcc3272f10c9a8ee2922` |
| `code/dataset.py` | `c453fb7d7e76b14971e0ee55e20c32332b85c928027db19f81d3caaac32dda31` |

`READY` contains the SHA256 of `manifest.json`. Evaluation must verify both the manifest and every frozen file before opening a 2024–2026 raster. The directory and files are read-only (555/444) so a later forecast cannot silently overwrite this freeze.

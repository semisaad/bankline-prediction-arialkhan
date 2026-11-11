# Water-mask audit (training period, 1989–2023)

## Encoding and polarity

| Item | Value | Evidence |
|---|---|---|
| Water class | 255 in band 1 (`water`) | Band description + elongated river network |
| Land class | 0 inside valid footprint | Surrounding floodplain, not water |
| Valid class | 255 in band 2 (`valid`) | Band description; 0 is a one-pixel border |

The water class is **not** inferred from display colour. The GeoTIFF band descriptions name band 1 `water` and band 2 `valid`, and the 255 water pixels form the connected meandering river plus ponds, while the 0 class is the surrounding land. The valid band removes a one-pixel edge where the focal operation has no data. Land and nodata are kept separate: invalid is never treated as land in change calculations.

## Grid and geometry

- CRS: `EPSG:32646` (metres)
- Grid: 355 × 478 pixels
- Pixel size: 30.0 m
- All historical files on the canonical grid without reprojection: True
- Valid footprint range: [162663, 162665] pixels

## Per-year class counts

| Year | Valid px | Water px | Land px | Invalid px |
|---:|---:|---:|---:|---:|
| 1989 | 162665 | 17223 | 145442 | 7025 |
| 1990 | 162665 | 16072 | 146593 | 7025 |
| 1991 | 162665 | 12735 | 149930 | 7025 |
| 1992 | 162665 | 16225 | 146440 | 7025 |
| 1993 | 162665 | 13334 | 149331 | 7025 |
| 1994 | 162665 | 11058 | 151607 | 7025 |
| 1995 | 162665 | 9613 | 153052 | 7025 |
| 1996 | 162663 | 14890 | 147773 | 7027 |
| 1998 | 162665 | 11164 | 151501 | 7025 |
| 1999 | 162665 | 12283 | 150382 | 7025 |
| 2000 | 162665 | 17520 | 145145 | 7025 |
| 2001 | 162665 | 23598 | 139067 | 7025 |
| 2002 | 162665 | 14215 | 148450 | 7025 |
| 2003 | 162665 | 11938 | 150727 | 7025 |
| 2004 | 162665 | 21448 | 141217 | 7025 |
| 2005 | 162665 | 10921 | 151744 | 7025 |
| 2006 | 162665 | 13603 | 149062 | 7025 |
| 2007 | 162665 | 11813 | 150852 | 7025 |
| 2008 | 162665 | 18643 | 144022 | 7025 |
| 2009 | 162665 | 11058 | 151607 | 7025 |
| 2010 | 162665 | 23408 | 139257 | 7025 |
| 2011 | 162665 | 15672 | 146993 | 7025 |
| 2012 | 162665 | 19053 | 143612 | 7025 |
| 2013 | 162665 | 12181 | 150484 | 7025 |
| 2014 | 162665 | 10918 | 151747 | 7025 |
| 2015 | 162665 | 10412 | 152253 | 7025 |
| 2016 | 162665 | 8754 | 153911 | 7025 |
| 2017 | 162665 | 8832 | 153833 | 7025 |
| 2018 | 162665 | 9158 | 153507 | 7025 |
| 2019 | 162665 | 9119 | 153546 | 7025 |
| 2020 | 162665 | 10513 | 152152 | 7025 |
| 2021 | 162665 | 8590 | 154075 | 7025 |
| 2022 | 162665 | 9493 | 153172 | 7025 |
| 2023 | 162665 | 7443 | 155222 | 7025 |

## Findings

- No historical raster is unreadable.
- All 34 historical rasters share one projected grid, one affine transform and one pixel size.
- The valid footprint is effectively constant (a one-pixel border).
- The water fraction varies strongly by year (about 4.6–14.5% of valid pixels), which is expected for a dry-season composite but is also a warning that water stage and detection sensitivity vary. Pixel transitions alone are therefore labelled *potential* erosion/accretion.
- Only the year is encoded in the filename. The export window is January 1–March 25; labels use 25 March as the nominal end date. This is a documented assumption, not an acquisition timestamp.

# Historical movement measurements (1989–2023)

## Product A — pixel change maps

For each consecutive pair of eligible observations, land→water is labelled **potential erosion** (+1) and water→land **potential accretion** (−1). Pixels invalid in either observation are nodata. Filtered maps remove connected patches smaller than 2 pixels; raw and filtered maps are both saved.

| Interval | Days | Erosion raw (m²) | Accretion raw (m²) | Erosion filtered (m²) | Accretion filtered (m²) |
|---|---:|---:|---:|---:|---:|
| 1989→1990 | 365 | 630000 | 1545300 | 558000 | 1489500 |
| 1990→1991 | 365 | 1049400 | 1541700 | 983700 | 1493100 |
| 1991→1992 | 366 | 2669400 | 955800 | 2576700 | 945900 |
| 1992→1993 | 365 | 468900 | 2137500 | 366300 | 2109600 |
| 1993→1994 | 365 | 1023300 | 706500 | 957600 | 656100 |
| 1994→1995 | 365 | 474300 | 893700 | 421200 | 829800 |
| 1995→1996 | 366 | 2155500 | 708300 | 2082600 | 681300 |
| 1996→1998 | 730 | 1577700 | 1844100 | 1488600 | 1826100 |
| 1998→1999 | 365 | 832500 | 465300 | 738900 | 406800 |
| 1999→2000 | 366 | 856800 | 776700 | 759600 | 729000 |
| 2000→2001 | 365 | 971100 | 762300 | 877500 | 702000 |
| 2001→2002 | 365 | 315000 | 1088100 | 236700 | 1005300 |
| 2002→2003 | 365 | 405000 | 202500 | 295200 | 157500 |
| 2003→2004 | 366 | 829800 | 471600 | 753300 | 420300 |
| 2004→2005 | 365 | 474300 | 784800 | 346500 | 746100 |
| 2005→2006 | 365 | 303300 | 437400 | 218700 | 351000 |
| 2006→2007 | 365 | 212400 | 570600 | 132300 | 482400 |
| 2007→2008 | 366 | 1063800 | 555300 | 989100 | 497700 |
| 2008→2009 | 365 | 444600 | 968400 | 366300 | 877500 |
| 2009→2010 | 365 | 867600 | 421200 | 783000 | 342900 |
| 2010→2011 | 365 | 463500 | 925200 | 365400 | 876600 |
| 2011→2012 | 366 | 792900 | 455400 | 682200 | 392400 |
| 2012→2013 | 365 | 125100 | 1627200 | 87300 | 1517400 |
| 2013→2014 | 365 | 225000 | 245700 | 155700 | 184500 |
| 2014→2015 | 365 | 137700 | 562500 | 103500 | 453600 |
| 2015→2016 | 366 | 257400 | 281700 | 198000 | 207900 |
| 2016→2017 | 365 | 287100 | 284400 | 216900 | 201600 |
| 2017→2018 | 365 | 675000 | 242100 | 598500 | 190800 |
| 2018→2019 | 365 | 135000 | 652500 | 96300 | 559800 |
| 2019→2020 | 366 | 262800 | 329400 | 179100 | 266400 |
| 2020→2021 | 365 | 308700 | 387900 | 255600 | 316800 |
| 2021→2022 | 365 | 328500 | 143100 | 222300 | 88200 |
| 2022→2023 | 365 | 117900 | 275400 | 72000 | 190800 |

## Product B — bankline migration

Bank displacement is measured along the fixed transect normal. Positive means outward, into land (erosion); negative means inward, toward the channel (accretion). The rate uses the nominal 25 March observation dates, so a missing year produces a two-year interval with two years of elapsed time rather than an assumed annual step.

- Raw bank-interval rows: 4950
- Quality counts: {'good': 3163, 'flagged': 1013, 'invalid': 646, 'implausible': 128}
- Sign counts among valid intervals: {'erosion_positive': 954, 'accretion_negative': 902, 'exact_zero': 2448}
- Good intervals by class (±15 m tolerance): {'low_movement': 2235, 'erosion': 443, 'accretion': 485}
- Elapsed-day range: [365, 730]

### Quality rules

- `good`: both banks valid, no multiple crossings, width at least 60 m, centre inside the river in both years, not a border transect, displacement ≤150 m, interval ≤5 years.
- `flagged`: valid but has a geometry warning (multiple crossings, centre outside, border).
- `implausible`: displacement >150 m (5 pixels) or interval >5 years.
- `invalid`: a bank intersection is missing.

Raw rows are preserved. Filtered rows contain only `good` intervals. The large number of `flagged` early-year rows reflects the fixed 2023 transects versus a channel that was in a different position; it is a label-quality limitation, not a hidden correction.

## Caveats

Water-mask transitions alone do not prove sediment erosion or deposition. Water level, seasonal wetness, cloud and classification error can all create apparent change. The 30 m pixel and the ±15 m low-movement tolerance are carried into the model evaluation.

# S7 Line - Station List

S-Bahn S7 of Munich, since the 2024 timetable split, runs between
**Wolfratshausen** and **München Hbf (Gleise 27–36)**.

The line no longer continues through the Stammstrecke to the eastern branch
(Höhenkirchen-Siegertsbrunn / Aying / Kreuzstraße); those stations are now
served by other S-Bahn lines.

## Stations (west → east)

| #  | Station                          | Notes                              |
|----|----------------------------------|------------------------------------|
| 1  | Wolfratshausen                   | Western terminus                   |
| 2  | Icking                           |                                    |
| 3  | Ebenhausen-Schäftlarn            |                                    |
| 4  | Hohenschäftlarn                  |                                    |
| 5  | **Baierbrunn**                   | EVA `8000781` (this project)       |
| 6  | Buchenhain                       |                                    |
| 7  | Höllriegelskreuth                |                                    |
| 8  | Pullach                          |                                    |
| 9  | Großhesselohe Isartalbahnhof     |                                    |
| 10 | München-Solln                    |                                    |
| 11 | München Siemenswerke             |                                    |
| 12 | München-Mittersendling           |                                    |
| 13 | München Harras                   |                                    |
| 14 | München Heimeranplatz            | U4/U5 transfer                     |
| 15 | München Donnersbergerbrücke      | Same-platform transfer to S1–S8    |
| 16 | München Hbf (Gleise 27–36)       | Eastern terminus                   |

The line operates a 20-minute clock-face headway most of the day; total
journey time end-to-end is ~40 minutes.

## Service pattern

- All trains stop at every station listed above (no skip-stop / express
  variants on S7).
- Direction names used in this project's data (`direction_bucket`):
  - `wolfratshausen` - terminus is `Wolfratshausen`.
  - `muenchen` - terminus contains `München` (typically the literal string
    `München Hbf Gl.27-36`).
  - `unknown` - anything else (e.g. cancelled / replacement service with an
    irregular destination).

## Direction inference (parser logic)

`fetcher/src/s7bb_fetcher/parser.py::classify_direction` uses the **last
segment** of the `<dp ppth>` attribute (departure path, pipe-separated) as
the terminus. Mid-path matches do not count - this matters because, after
the 2024 split, an S7 train will never legitimately have `München` mid-path
and a non-München terminus.

## Sources

- `documentation/db-api/timetables-api.md` - DB Timetables API endpoints used
  to fetch this data live.
- Real plan XML for Baierbrunn (`/plan/8000781/<YYMMDD>/<HH>`) - the
  authoritative source for the actual current station sequence; the table
  above was derived from `<ar ppth>` + `<dp ppth>` of S7 stops at Baierbrunn.
- München Wiki: <https://www.muenchenwiki.de/wiki/S-Bahnlinie_7>
- S-Bahn München (official): <https://www.s-bahn-muenchen.de/de/fahren/baustellen/s7>
- Bayerisches Landesportal - 2024 split announcement:
  <https://www.bayern.de/neue-s-bahnlinie-s5-teilung-der-s7/>

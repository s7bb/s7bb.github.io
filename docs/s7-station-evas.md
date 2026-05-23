# S7 station EVAs — canonical reference

**Use this file first for any EVA lookup.** Avoid hitting
`/station/{name}` on the DB Timetables API when the answer is already
here — quota is finite and every avoidable call is wasted budget.

Only query the API when:
- a station name appears in `dp_ppth` that is not listed below, or
- DB notifies of an EVA change (rare; would show up as a
  `terminus_health` zero-match streak warning first).

When you do query, **append the result to this file in the same PR**.

## Provenance

All EVAs below were resolved against
`https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1/station/{pattern}`
on **2026-05-23** using the project's `DB_API_KEY` /
`DB_CLIENT_ID`. Each row carries the API's reported `name`, primary
`eva`, and `ds100` code. `meta` (sibling EVAs from the API response)
is included only where it disambiguates surface vs. tief variants or
points to a separate S-Bahn-only sub-entity.

## Lookup tables

### S7-Süd: Wolfratshausen → Baierbrunn

Route order south to north. The Wolfratshausen end is the southwest
terminus; trains turn around and head north toward München.

| EVA       | DS100  | Name                  | Notes                                  |
|-----------|--------|-----------------------|----------------------------------------|
| `8006550` | MWO    | Wolfratshausen        | Southwest terminus (`wolfratshausen` bucket). |
| `8003039` | MIC    | Icking                |                                        |
| `8001621` | MEBS   | Ebenhausen-Schäftlarn |                                        |
| `8002955` | MHSL   | Hohenschäftlarn       |                                        |
| `8000781` | MBAB   | **Baierbrunn**        | **S7BB target station** (`S7BB_EVA` default). |

### S7-Süd: Baierbrunn → München Hbf (Isartal valley)

Route order south to north along the Isartal line into München.

| EVA       | DS100  | Name                          | Notes                          |
|-----------|--------|-------------------------------|--------------------------------|
| `8071272` | —      | Buchenhain                    | No DS100 in API response.      |
| `8002899` | MHRK   | Höllriegelskreuth             |                                |
| `8004899` | MPUL   | Pullach                       |                                |
| `8002422` | MGOI   | Großhesselohe Isartalbf       |                                |
| `8004161` | MSN    | München-Solln                 |                                |
| `8004137` | MSW    | München Siemenswerke          |                                |
| `8004154` | MMT    | München-Mittersendling        |                                |
| `8004130` | MHAR   | München Harras                |                                |
| `8005419` | MHP    | München Heimeranplatz         |                                |
| `8004128` | MMDN   | München Donnersbergerbrücke   |                                |

### München Hbf — multi-EVA terminus

All three Hbf entities share `meta="270002|8000261|8098261|8098262|8098263"`
in the API response. The `8000261` (long-distance) variant is NOT used
by the S7 — kept here only as a "do not poll" pointer.

| EVA       | DS100  | Name                  | Use                                                  |
|-----------|--------|-----------------------|------------------------------------------------------|
| `8098261` | MH  N  | München Hbf Gl.27-36  | Surface S-Bahn platforms. Original `muenchen` terminus EVA. |
| `8098263` | MHT    | München Hbf (tief)    | Stammstrecke S-Bahn. Added 2026-05-23 (`muenchen` multi-EVA fix). |
| `8098262` | MH  S  | München Hbf Gl.5-10   | Additional surface platforms, NOT on S7 routing. **Do not poll.** |
| `8000261` | MH     | München Hbf           | Long-distance platforms (ICE / IC / EC). **Do not poll** — was the original misconfiguration that caused the v0.6.x terminus tracking bug. |

### Stammstrecke (München Hbf tief → Ostbahnhof)

Underground east of Hbf. S7 calls at all of these when routed via
tief. Currently not in `STATION_NAME_TO_EVA` in code — only Hbf-tief
itself is added in v0.8.3. Listed here for the drilldown cap design
in [muenchen-hbf-multi-eva-design](superpowers/specs/2026-05-23-muenchen-hbf-multi-eva-design.md):
stations east of Hbf are intentionally truncated from drilldown
walks, so they don't need a code mapping today. They are documented
here in case future work (e.g. reachability tiers) needs them.

| EVA       | DS100  | Name                                  |
|-----------|--------|---------------------------------------|
| `8004132` | MKA    | München Karlsplatz (Stachus)          |
| `8004135` | MMP    | München Marienplatz                   |
| `8004131` | MIT    | München Isartor                       |
| `8004136` | MRP    | München Rosenheimer Platz             |
| `8000262` | MOP    | München Ost (Ostbahnhof)              |

### S7-Ost: Ostbahnhof → Kreuzstraße / Aying

East of Ostbahnhof the S7 splits — most trains run all the way to
Kreuzstraße; some short-turn at Höhenkirchen-Siegertsbrunn or Aying.
Not in `STATION_NAME_TO_EVA`; the drilldown cap at Hbf means these
are never walked.

| EVA       | DS100  | Name                          |
|-----------|--------|-------------------------------|
| `8004134` | MLEU   | München Leuchtenbergring      |
| `8004142` | MBAL   | München-Berg am Laim          |
| `8004162` | MTR    | München-Trudering             |
| `8002383` | MGDF   | Gronsdorf                     |
| `8002491` | MHR    | Haar                          |
| `8006059` | MVS    | Vaterstetten                  |
| `8000785` | MBDH   | Baldham                       |
| `8006671` | MZO    | Zorneding                     |
| `8006131` | MWAE   | Wächterhof                    |
| `8002894` | MHSB   | Höhenkirchen-Siegertsbrunn    |
| `8001578` | MDHR   | Dürrnhaar                     |
| `8000675` | MAY    | Aying                         |
| `8004761` | MPEI   | Peiß                          |
| `8002420` | MGHD   | Großhelfendorf                |
| `8003438` | MKZ    | Kreuzstraße                   |

## Code cross-reference

`fetcher/src/s7bb_fetcher/terminus.py` holds the runtime subset
(`STATION_NAME_TO_EVA` + `MUENCHEN_HBF_EVA` / `WOLFRATSHAUSEN_EVA` /
`MUENCHEN_HBF_TIEF_EVA` constants). When adding a station to that
map, copy the `name` string verbatim from the table above — it must
match what DB emits in `dp_ppth`, including diacritics and "(tief)"
parenthetical.

`fetcher/src/s7bb_fetcher/api.py` holds the Baierbrunn EVA default
(`BAIERBRUNN_EVA = "8000781"`), overridable via `S7BB_EVA`.

## How to extend this file

If a new station appears in production data (e.g. DB re-routes S7
through a new station, or a sibling tief variant is introduced):

1. Query the API once: `GET /station/{name-or-eva}` using the
   project credentials. The snippet below works in a python shell
   inside the repo with `.env` loaded:

   ```python
   import os, requests
   from urllib.parse import quote
   h = {"DB-Api-Key": os.environ["DB_API_KEY"],
        "DB-Client-Id": os.environ.get("DB_CLIENT_ID",""),
        "Accept": "application/xml"}
   r = requests.get(
       "https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1/station/"
       + quote("<name or eva>"),
       headers=h, timeout=10)
   print(r.text)
   ```

2. Add the row to the appropriate table above with `eva`, `ds100`,
   `name`, and a short note on its role.

3. If the resolution corrected an existing entry, bump the
   **Provenance** date at the top of this file and reference the
   PR / spec that triggered the update.

# uvexevents

A dependency-light MicroPython client for the [Public VEX Events API v2](https://events.vex.com/api/v2/swagger.yml)
(the API that backs [events.vex.com](https://events.vex.com)). Built for
running on microcontrollers (ESP32, ESP8266, Raspberry Pi Pico W, etc.) as
well as the MicroPython Unix port, and tested against real
[MicroPython](https://micropython.org) (v1.28).

It covers all 20 read endpoints in the spec: Events, Teams, Programs, and
Seasons, including their nested sub-resources (a division's matches and
rankings, a team's skills runs and awards, and so on).

The whole library is a single file, `uvexevents.py`, that compiles to a
single `uvexevents.mpy` with `mpy-cross` - one file to copy to a device,
no package directory required.

## Requirements

- MicroPython (any port with networking + `ujson`, or the Unix port).
- An HTTP client module: [`urequests`](https://github.com/micropython/micropython-lib/tree/master/python-ecosys/urequests)
  (install on-device with `mip.install("urequests")`, or `mpremote mip install urequests`),
  or a port that already provides a `requests` module. `uvexevents` picks
  whichever is importable at runtime.
- A VEX Events API bearer token. Generate one from your events.vex.com
  account (Developer / API settings) - it's a JWT, passed as
  `Authorization: Bearer <token>` on every request.

## Install

There's no PyPI/mip registry entry published for this yet, so install by
copying the single file directly:

```
mpremote cp uvexevents.py :lib/uvexevents.py
mpremote mip install urequests
```

Or, if you froze/hosted this repo somewhere `mip` can reach it, adjust the
GitHub URL in `package.json` to point at your fork and run
`mpremote mip install github:you/uvexevents`.

For flash-constrained boards (ESP8266), ship the precompiled
`uvexevents.mpy` instead (built with mpy-cross v6.3, matching
MicroPython 1.28 — see "MicroPython version compatibility" below).
`.mpy` bytecode takes precedence over a same-named `.py` file at import
time, and it's roughly 70% smaller (28 KB of source compiles to an
8 KB `.mpy`):

```
mpremote cp uvexevents.mpy :lib/uvexevents.mpy
```

To regenerate it yourself after editing `uvexevents.py`:

```
mpy-cross uvexevents.py -o uvexevents.mpy
```

Because everything lives in one file, this always produces exactly one
`.mpy` — there's no separate freezing/bundling step needed to combine
multiple modules the way a multi-file package would require.

### MicroPython version compatibility

`.mpy` files embed a bytecode format version (the "mpy version") that
must match the MicroPython firmware loading them — e.g. mpy-cross v6.3
output (this repo's precompiled file) loads on MicroPython 1.20 through
at least 1.28, but a firmware outside that range will refuse to import
it with a version-mismatch error. Check compatibility with
`sys.implementation._mpy` on the board (an integer encoding the
supported bytecode version + feature flags) versus what your
`mpy-cross --version` emits; if they don't line up, recompile
`uvexevents.py` using the `mpy-cross` binary that ships alongside your
board's firmware/SDK rather than using the checked-in `.mpy` file. When
in doubt, just ship `uvexevents.py` — it's portable across any version.

## Quickstart

```python
from uvexevents import VexEventsClient

client = VexEventsClient(token="<your JWT>")

# Every get_* method returns one page as a plain dict: {"meta": {...}, "data": [...]}
page = client.get_events(seasons=[181], levels=["World"], per_page=10)
for event in page["data"]:
    print(event["sku"], event["name"])

# Every iter_* method is a generator that walks all pages automatically
# and yields individual items - the memory-friendly way to consume a
# full result set on a microcontroller.
for team in client.iter_event_teams(page["data"][0]["id"]):
    print(team["number"], team.get("team_name"))
```

See `examples/` for a full ESP32 WiFi walkthrough, manual vs. automatic
pagination, and error handling.

## Design notes

- **One class, `VexEventsClient`.** No sessions, no connection pooling -
  each call opens and closes its own socket via `urequests`, matching how
  `urequests` itself works and keeping resource usage predictable on
  small devices.
- **`get_*` vs. `iter_*`.** Every list endpoint has both: `get_X(...)`
  fetches exactly one page (you control `page`/`per_page`, and get back
  the raw `meta`/`data` dict — handy for building a paged UI or a
  "load more" button); `iter_X(...)` is a generator that fetches
  pages lazily and yields one item at a time, walking `meta.current_page`
  / `meta.last_page` until exhausted. Prefer `iter_*` unless you
  specifically need page metadata or a specific page.
- **Filter parameters are plural where the API takes an array** (e.g.
  `seasons=[181, 182]` maps to the API's `season[]=181&season[]=182`), and
  singular where it takes a scalar (e.g. `region="CA"`, `registered=True`).
  Pass `None` (the default) to omit a filter entirely.
- **Errors** are typed exceptions (see below), not error dicts or return
  codes, so a normal `try/except` works and you can't accidentally
  ignore a failure.
- **No `enum` module dependency.** MicroPython doesn't reliably ship
  `enum`, so `uvexevents` exposes plain classes of string/int constants
  instead (`EventLevel.WORLD == "World"`). Passing the raw string is
  equally valid — the constants exist for autocomplete/typo protection,
  not validation.
- **Single file, flat namespace.** Everything - the client, exceptions,
  and constants classes - is defined directly in `uvexevents.py` and
  importable straight from `uvexevents` (e.g. `from uvexevents import
  VexEventsClient, VexEventsNotFoundError, EventLevel`). There are no
  `uvexevents.errors` or `uvexevents.constants` submodules to import
  from separately.

## API reference

All methods live on `VexEventsClient`. `page`/`per_page` (default 25, max
250 per the API) are accepted by every `get_*` list method; `per_page`
alone is accepted by every `iter_*` method (page is managed internally).

### Events

| Method | API operation | Notes |
|---|---|---|
| `get_events(ids, skus, teams, seasons, start, end, region, levels, my_events, event_types, page, per_page)` / `iter_events(...)` | `event_getEvents` | List/search events |
| `get_event(event_id)` | `event_getEvent` | Single event; raises `VexEventsNotFoundError` if unknown |
| `get_event_teams(event_id, numbers, registered, grades, countries, my_teams, page, per_page)` / `iter_event_teams(...)` | `event_getTeams` | Teams present at an event |
| `get_event_skills(event_id, teams, types, page, per_page)` / `iter_event_skills(...)` | `event_getSkills` | Skills runs at an event |
| `get_event_awards(event_id, teams, winners, page, per_page)` / `iter_event_awards(...)` | `event_getAwards` | Awards given at an event |
| `get_event_division_matches(event_id, division_id, teams, rounds, instances, matchnums, page, per_page)` / `iter_event_division_matches(...)` | `event_getDivisionMatches` | Matches in one division |
| `get_event_division_rankings(event_id, division_id, teams, ranks, page, per_page)` / `iter_event_division_rankings(...)` | `event_getDivisionRankings` | Qual rankings in one division |
| `get_event_division_finalist_rankings(event_id, division_id, teams, ranks, page, per_page)` / `iter_event_division_finalist_rankings(...)` | `event_getDivisionFinalistRankings` | Finalist rankings in one division |

### Teams

| Method | API operation | Notes |
|---|---|---|
| `get_teams(ids, numbers, events, registered, programs, grades, countries, my_teams, page, per_page)` / `iter_teams(...)` | `team_getTeams` | List/search teams |
| `get_team(team_id)` | `team_getTeam` | Single team; raises `VexEventsNotFoundError` if unknown |
| `get_team_events(team_id, skus, seasons, start, end, levels, page, per_page)` / `iter_team_events(...)` | `team_getEvents` | Events a team attended |
| `get_team_matches(team_id, events, seasons, rounds, instances, matchnums, page, per_page)` / `iter_team_matches(...)` | `team_getMatches` | Matches a team played |
| `get_team_rankings(team_id, events, ranks, seasons, page, per_page)` / `iter_team_rankings(...)` | `team_getRankings` | Rankings a team achieved |
| `get_team_skills(team_id, events, types, seasons, page, per_page)` / `iter_team_skills(...)` | `team_getSkills` | Skills runs a team performed |
| `get_team_awards(team_id, events, seasons, page, per_page)` / `iter_team_awards(...)` | `team_getAwards` | Awards a team received |

### Programs

| Method | API operation | Notes |
|---|---|---|
| `get_program(program_id)` | `program_getProgram` | Single program |
| `get_programs(ids, page, per_page)` / `iter_programs(...)` | `program_getPrograms` | List programs |

### Seasons

| Method | API operation | Notes |
|---|---|---|
| `get_seasons(ids, programs, teams, start, end, active, page, per_page)` / `iter_seasons(...)` | `season_getSeasons` | List/search seasons |
| `get_season(season_id)` | `season_getSeason` | Single season |
| `get_season_events(season_id, skus, teams, start, end, levels, page, per_page)` / `iter_season_events(...)` | `season_getEvents` | Events in a season |

`start`/`end` filters take an RFC3339 datetime string (e.g.
`"2024-01-01T00:00:00Z"`), matching what the API expects.

## Errors

All exceptions are importable directly from `uvexevents` and subclass
`VexEventsError`, which has `.message`, `.code` (the API's own error
code, if any) and `.status` (HTTP status code, `None` for connection
failures):

- `VexEventsConnectionError` - the request itself failed (no network,
  DNS, TLS, timeout) before any HTTP response was received.
- `VexEventsHTTPError` - the API responded with a 4xx/5xx status.
  - `VexEventsNotFoundError` - 404 (unknown event/team/program/season id).
  - `VexEventsAuthError` - 401/403 (missing, invalid, or expired token).

```python
from uvexevents import VexEventsError, VexEventsNotFoundError

try:
    client.get_team(999999999)
except VexEventsNotFoundError:
    print("no such team")
except VexEventsError as exc:
    print("something else went wrong:", exc)
```

## Constants

Importable directly from `uvexevents`:

- `EventType` - `TOURNAMENT`, `LEAGUE`, `WORKSHOP`, `VIRTUAL`
- `EventLevel` - `WORLD`, `NATIONAL`, `REGIONAL`, `STATE`, `SIGNATURE`, `OTHER`
- `Grade` - `COLLEGE`, `HIGH_SCHOOL`, `MIDDLE_SCHOOL`, `ELEMENTARY_SCHOOL`
- `SkillType` - `DRIVER`, `PROGRAMMING`, `PACKAGE_DELIVERY_TIME`
- `AllianceColor` - `RED`, `BLUE`
- `AwardDesignation` - `TOURNAMENT`, `DIVISION`
- `AwardClassification` - `CHAMPION`, `FINALIST`, `SEMIFINALIST`, `QUARTERFINALIST`
- `MatchRound` - `PRACTICE` (1), `QUALIFICATION` (2), `QUARTERFINALS` (3),
  `SEMIFINALS` (4), `FINALS` (5), `ROUND_OF_16` (6) - the API documents
  these as "typical values"; other integers can appear for
  program-specific bracket formats.

## Response shapes

Responses are returned as plain `dict`/`list` (decoded straight from
JSON), matching the schemas in the OpenAPI spec:

- List endpoints return `{"meta": {...page info...}, "data": [...]}`.
  `meta` includes `current_page`, `last_page`, `per_page`, `total`, etc.
- Single-item endpoints (`get_event`, `get_team`, `get_program`,
  `get_season`) return the object dict directly.
- Nested references (an event's `season`, a match's `event`/`division`, a
  ranking's `team`, etc.) are small `{"id": ..., "name": ..., "code": ...}`
  dicts, per the spec's `IdInfo` schema.

Refer to the [swagger spec](https://events.vex.com/api/v2/swagger.yml)
for the exact field list per object type (`Event`, `Team`, `MatchObj`,
`Alliance`, `Ranking`, `Skill`, `Award`, `Program`, `Season`, ...).

## A note on MicroPython dict ordering

Query parameters are built from plain `dict`s. MicroPython's dict
implementation only preserves insertion order for small dicts; beyond
roughly 8 entries it falls back to unordered hash storage. This library
never depends on parameter order (and neither does the API), but it's
worth knowing if you inspect `_build_query()`'s output directly - the
same filters can produce query strings with parameters in a different
order across runs.

## Testing

`uvexevents.py` has no import-time dependency on real sockets, so it can
be exercised under the MicroPython Unix port with a fake `urequests`
module substituted via `sys.modules` (see the test approach used during
development: a `FakeResponse`/`get()` stand-in that records calls and
returns scripted `(status_code, json_body)` pairs, keyed by path +
sorted query params to sidestep the dict-ordering behavior above). The
same test suite was run against both `uvexevents.py` and the compiled
`uvexevents.mpy` in isolation (i.e. with no `.py` source present) to
confirm the bytecode behaves identically.

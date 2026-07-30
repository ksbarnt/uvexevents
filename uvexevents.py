"""uvexevents - a MicroPython client for the Public VEX Events API v2.

Single-file module (compiles to one uvexevents.mpy with mpy-cross) for
https://events.vex.com/api/v2 (API version 1.0.21, spec at
https://events.vex.com/api/v2/swagger.yml).

    from uvexevents import VexEventsClient

    client = VexEventsClient(token="<your JWT>")
    page = client.get_events(seasons=[181])
    print(page["data"])

See README.md for the full guide and API reference.
"""

# -- compat shims ------------------------------------------------------
#
# Picks whichever JSON / HTTP client modules are available on the running
# MicroPython port (or CPython, for local testing), and provides a tiny,
# dependency-free percent-encoder since urllib.parse is not guaranteed to
# exist on MicroPython. Names here are underscore-prefixed: they're
# implementation details, not part of the public API.

try:
    import ujson as _json
except ImportError:
    import json as _json

try:
    import urequests as _http
except ImportError:
    try:
        import requests as _http
    except ImportError:
        _http = None

# Characters that never need percent-encoding in a query string. '[' and ']'
# are included because the VEX Events API uses PHP-style array parameters
# (e.g. "id[]=1&id[]=2") and virtually every HTTP server/client tolerates
# literal brackets there, even though RFC 3986 marks them as gen-delims.
_SAFE = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ"
         "abcdefghijklmnopqrstuvwxyz"
         "0123456789-_.~[]")


def _quote(value):
    """Percent-encode ``value`` (coerced to str) for use in a query string."""
    s = value if isinstance(value, str) else str(value)
    out = []
    for ch in s:
        if ch in _SAFE:
            out.append(ch)
        elif ch == " ":
            out.append("%20")
        else:
            for b in ch.encode("utf-8"):
                out.append("%%%02X" % b)
    return "".join(out)


def _stringify(value):
    """Convert a Python value into the wire representation the API expects."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _build_query(params):
    """Turn a dict of scalars/lists into a "key=value&key=value" string.

    ``None`` values (and ``None`` items inside lists) are skipped, so every
    endpoint method below can pass every filter unconditionally and let
    unset ones disappear. List values produce repeated ``key[]=item`` pairs
    per the API's "form, explode: true" array style.
    """
    parts = []
    for key in params:
        value = params[key]
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            for item in value:
                if item is None:
                    continue
                parts.append(_quote(key) + "=" + _quote(_stringify(item)))
        else:
            parts.append(_quote(key) + "=" + _quote(_stringify(value)))
    return "&".join(parts)


# -- constants -----------------------------------------------------------
#
# MicroPython does not reliably ship the `enum` module, so these are plain
# classes of string/int constants instead. Passing any of these -- or just
# the raw string/int value -- to a client method works identically; they
# exist purely so you can write EventLevel.WORLD instead of "World" and get
# a NameError instead of silently filtering on a typo.

class EventType(object):
    """Values for the Event.event_type field / events(...) event_types filter."""
    TOURNAMENT = "tournament"
    LEAGUE = "league"
    WORKSHOP = "workshop"
    VIRTUAL = "virtual"


class EventLevel(object):
    """Values for the Event.level field / events(...) levels filter.

    Note: the /events, /teams/{id}/events and /seasons/{id}/events filters
    do not accept REGIONAL (only the Event object itself can have that
    level) -- passing it as a filter will simply match zero events.
    """
    WORLD = "World"
    NATIONAL = "National"
    REGIONAL = "Regional"
    STATE = "State"
    SIGNATURE = "Signature"
    OTHER = "Other"


class Grade(object):
    """Values for the Team.grade field / grades filter."""
    COLLEGE = "College"
    HIGH_SCHOOL = "High School"
    MIDDLE_SCHOOL = "Middle School"
    ELEMENTARY_SCHOOL = "Elementary School"


class SkillType(object):
    """Values for the Skill.type field / skills(...) types filter."""
    DRIVER = "driver"
    PROGRAMMING = "programming"
    PACKAGE_DELIVERY_TIME = "package_delivery_time"


class AllianceColor(object):
    """Values for Alliance.color."""
    RED = "red"
    BLUE = "blue"


class AwardDesignation(object):
    """Values for Award.designation."""
    TOURNAMENT = "tournament"
    DIVISION = "division"


class AwardClassification(object):
    """Values for Award.classification."""
    CHAMPION = "champion"
    FINALIST = "finalist"
    SEMIFINALIST = "semifinalist"
    QUARTERFINALIST = "quarterfinalist"


class MatchRound(object):
    """Common values for MatchObj.round / matches(...) rounds filter.

    The API documents these as "typical values" -- other integers may
    appear for program-specific bracket formats.
    """
    PRACTICE = 1
    QUALIFICATION = 2
    QUARTERFINALS = 3
    SEMIFINALS = 4
    FINALS = 5
    ROUND_OF_16 = 6


# -- errors ----------------------------------------------------------------

class VexEventsError(Exception):
    """Base error for all problems talking to the VEX Events API."""

    def __init__(self, message, code=None, status=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status

    def __str__(self):
        if self.status is not None:
            return "[HTTP %s] %s" % (self.status, self.message)
        return str(self.message)


class VexEventsConnectionError(VexEventsError):
    """Raised when the underlying socket/HTTP request itself fails.

    This covers no-network, DNS failure, TLS errors, timeouts, etc. -
    anything that happens before a response is received from the server.
    """
    pass


class VexEventsHTTPError(VexEventsError):
    """Raised when the API responds with a 4xx/5xx status code."""
    pass


class VexEventsNotFoundError(VexEventsHTTPError):
    """Raised for 404 responses (e.g. an unknown event/team/program/season id)."""
    pass


class VexEventsAuthError(VexEventsHTTPError):
    """Raised for 401/403 responses (missing, invalid, or expired bearer token)."""
    pass


# -- client ------------------------------------------------------------

DEFAULT_BASE_URL = "https://events.vex.com/api/v2"


class VexEventsClient(object):
    """A small HTTP client for https://events.vex.com/api/v2.

    Example::

        from uvexevents import VexEventsClient

        client = VexEventsClient(token="<your JWT>")
        page = client.get_events(seasons=[181], levels=["World"])
        for event in page["data"]:
            print(event["sku"], event["name"])

    All ``get_*`` methods return a single page as the raw decoded JSON
    dict (with ``"meta"`` and ``"data"`` keys, matching the API
    response shape). All ``iter_*`` methods are generators that walk
    every page automatically and yield individual items, which is the
    easiest way to consume a full result set on a memory-constrained
    device without holding every page in RAM at once.
    """

    def __init__(self, token=None, base_url=DEFAULT_BASE_URL, timeout=10):
        """
        :param token: Bearer/JWT token from your events.vex.com account.
            Passed as ``Authorization: Bearer <token>`` on every request.
        :param base_url: Override the API root (mainly useful for testing
            against a mock server). Must not have a trailing slash.
        :param timeout: Socket timeout in seconds, passed through to the
            underlying HTTP client when it supports one.
        """
        self.token = token
        self.base_url = base_url
        self.timeout = timeout

    # -- low-level plumbing --------------------------------------------

    def _headers(self):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        return headers

    def _request(self, path, query=None):
        if _http is None:
            raise VexEventsConnectionError(
                "No HTTP client module found. Install 'urequests' via "
                "mip: mip.install('urequests') (or 'requests' on ports "
                "that bundle it), then retry."
            )
        url = self.base_url + path
        if query:
            qs = _build_query(query)
            if qs:
                url += "?" + qs
        headers = self._headers()
        try:
            try:
                resp = _http.get(url, headers=headers, timeout=self.timeout)
            except TypeError:
                # Some urequests builds don't accept a timeout kwarg.
                resp = _http.get(url, headers=headers)
        except Exception as exc:
            raise VexEventsConnectionError(
                "Request to %s failed: %s" % (url, exc)
            )
        try:
            return self._handle_response(resp, url)
        finally:
            try:
                resp.close()
            except Exception:
                pass

    def _handle_response(self, resp, url):
        status = resp.status_code
        if status >= 400:
            payload = None
            try:
                payload = resp.json()
            except Exception:
                payload = None
            message = None
            code = None
            if isinstance(payload, dict):
                message = payload.get("message")
                code = payload.get("code")
            if not message:
                message = "HTTP %s error for %s" % (status, url)
            if status == 404:
                raise VexEventsNotFoundError(message, code=code, status=status)
            if status in (401, 403):
                raise VexEventsAuthError(message, code=code, status=status)
            raise VexEventsHTTPError(message, code=code, status=status)
        try:
            return resp.json()
        except Exception as exc:
            raise VexEventsError(
                "Could not decode JSON response from %s: %s" % (url, exc)
            )

    def _paginated_request(self, path, query, page=None, per_page=None):
        q = dict(query) if query else {}
        if page is not None:
            q["page"] = page
        if per_page is not None:
            q["per_page"] = per_page
        return self._request(path, q)

    def _iter_pages(self, path, query, per_page=None):
        page = 1
        while True:
            result = self._paginated_request(path, query, page=page, per_page=per_page)
            yield result
            meta = result.get("meta") or {}
            last_page = meta.get("last_page")
            current_page = meta.get("current_page", page)
            if not last_page or current_page >= last_page:
                break
            page = current_page + 1

    def _iter_items(self, path, query, per_page=None):
        for result in self._iter_pages(path, query, per_page=per_page):
            for item in (result.get("data") or []):
                yield item

    # -- Events ----------------------------------------------------------

    def _events_query(self, ids=None, skus=None, teams=None, seasons=None,
                       start=None, end=None, region=None, levels=None,
                       my_events=None, event_types=None):
        return {
            "id[]": ids,
            "sku[]": skus,
            "team[]": teams,
            "season[]": seasons,
            "start": start,
            "end": end,
            "region": region,
            "level[]": levels,
            "myEvents": my_events,
            "eventTypes[]": event_types,
        }

    def get_events(self, ids=None, skus=None, teams=None, seasons=None,
                    start=None, end=None, region=None, levels=None,
                    my_events=None, event_types=None, page=None, per_page=None):
        """GET /events - one page of Events matching the given filters."""
        query = self._events_query(ids, skus, teams, seasons, start, end,
                                    region, levels, my_events, event_types)
        return self._paginated_request("/events", query, page=page, per_page=per_page)

    def iter_events(self, ids=None, skus=None, teams=None, seasons=None,
                     start=None, end=None, region=None, levels=None,
                     my_events=None, event_types=None, per_page=None):
        """GET /events - generator yielding every matching Event across all pages."""
        query = self._events_query(ids, skus, teams, seasons, start, end,
                                    region, levels, my_events, event_types)
        return self._iter_items("/events", query, per_page=per_page)

    def get_event(self, event_id):
        """GET /events/{id} - a single Event, or raises VexEventsNotFoundError."""
        return self._request("/events/%s" % event_id)

    def get_event_teams(self, event_id, numbers=None, registered=None,
                         grades=None, countries=None, my_teams=None,
                         page=None, per_page=None):
        """GET /events/{id}/teams - one page of Teams present at an Event."""
        query = {
            "number[]": numbers,
            "registered": registered,
            "grade[]": grades,
            "country[]": countries,
            "myTeams": my_teams,
        }
        return self._paginated_request(
            "/events/%s/teams" % event_id, query, page=page, per_page=per_page)

    def iter_event_teams(self, event_id, numbers=None, registered=None,
                          grades=None, countries=None, my_teams=None, per_page=None):
        """GET /events/{id}/teams - generator over every matching Team."""
        query = {
            "number[]": numbers,
            "registered": registered,
            "grade[]": grades,
            "country[]": countries,
            "myTeams": my_teams,
        }
        return self._iter_items("/events/%s/teams" % event_id, query, per_page=per_page)

    def get_event_skills(self, event_id, teams=None, types=None, page=None, per_page=None):
        """GET /events/{id}/skills - one page of Skills runs at an Event."""
        query = {"team[]": teams, "type[]": types}
        return self._paginated_request(
            "/events/%s/skills" % event_id, query, page=page, per_page=per_page)

    def iter_event_skills(self, event_id, teams=None, types=None, per_page=None):
        """GET /events/{id}/skills - generator over every matching Skill run."""
        query = {"team[]": teams, "type[]": types}
        return self._iter_items("/events/%s/skills" % event_id, query, per_page=per_page)

    def get_event_awards(self, event_id, teams=None, winners=None, page=None, per_page=None):
        """GET /events/{id}/awards - one page of Awards given at an Event."""
        query = {"team[]": teams, "winner[]": winners}
        return self._paginated_request(
            "/events/%s/awards" % event_id, query, page=page, per_page=per_page)

    def iter_event_awards(self, event_id, teams=None, winners=None, per_page=None):
        """GET /events/{id}/awards - generator over every matching Award."""
        query = {"team[]": teams, "winner[]": winners}
        return self._iter_items("/events/%s/awards" % event_id, query, per_page=per_page)

    def get_event_division_matches(self, event_id, division_id, teams=None,
                                    rounds=None, instances=None, matchnums=None,
                                    page=None, per_page=None):
        """GET /events/{id}/divisions/{div}/matches - one page of Matches."""
        query = {
            "team[]": teams,
            "round[]": rounds,
            "instance[]": instances,
            "matchnum[]": matchnums,
        }
        return self._paginated_request(
            "/events/%s/divisions/%s/matches" % (event_id, division_id),
            query, page=page, per_page=per_page)

    def iter_event_division_matches(self, event_id, division_id, teams=None,
                                     rounds=None, instances=None, matchnums=None,
                                     per_page=None):
        """GET /events/{id}/divisions/{div}/matches - generator over every Match."""
        query = {
            "team[]": teams,
            "round[]": rounds,
            "instance[]": instances,
            "matchnum[]": matchnums,
        }
        return self._iter_items(
            "/events/%s/divisions/%s/matches" % (event_id, division_id),
            query, per_page=per_page)

    def get_event_division_finalist_rankings(self, event_id, division_id,
                                              teams=None, ranks=None,
                                              page=None, per_page=None):
        """GET /events/{id}/divisions/{div}/finalistRankings - one page of Rankings."""
        query = {"team[]": teams, "rank[]": ranks}
        return self._paginated_request(
            "/events/%s/divisions/%s/finalistRankings" % (event_id, division_id),
            query, page=page, per_page=per_page)

    def iter_event_division_finalist_rankings(self, event_id, division_id,
                                               teams=None, ranks=None, per_page=None):
        """GET /events/{id}/divisions/{div}/finalistRankings - generator over every Ranking."""
        query = {"team[]": teams, "rank[]": ranks}
        return self._iter_items(
            "/events/%s/divisions/%s/finalistRankings" % (event_id, division_id),
            query, per_page=per_page)

    def get_event_division_rankings(self, event_id, division_id, teams=None,
                                     ranks=None, page=None, per_page=None):
        """GET /events/{id}/divisions/{div}/rankings - one page of Rankings."""
        query = {"team[]": teams, "rank[]": ranks}
        return self._paginated_request(
            "/events/%s/divisions/%s/rankings" % (event_id, division_id),
            query, page=page, per_page=per_page)

    def iter_event_division_rankings(self, event_id, division_id, teams=None,
                                      ranks=None, per_page=None):
        """GET /events/{id}/divisions/{div}/rankings - generator over every Ranking."""
        query = {"team[]": teams, "rank[]": ranks}
        return self._iter_items(
            "/events/%s/divisions/%s/rankings" % (event_id, division_id),
            query, per_page=per_page)

    # -- Teams -------------------------------------------------------------

    def _teams_query(self, ids=None, numbers=None, events=None, registered=None,
                      programs=None, grades=None, countries=None, my_teams=None):
        return {
            "id[]": ids,
            "number[]": numbers,
            "event[]": events,
            "registered": registered,
            "program[]": programs,
            "grade[]": grades,
            "country[]": countries,
            "myTeams": my_teams,
        }

    def get_teams(self, ids=None, numbers=None, events=None, registered=None,
                  programs=None, grades=None, countries=None, my_teams=None,
                  page=None, per_page=None):
        """GET /teams - one page of Teams matching the given filters."""
        query = self._teams_query(ids, numbers, events, registered, programs,
                                   grades, countries, my_teams)
        return self._paginated_request("/teams", query, page=page, per_page=per_page)

    def iter_teams(self, ids=None, numbers=None, events=None, registered=None,
                    programs=None, grades=None, countries=None, my_teams=None,
                    per_page=None):
        """GET /teams - generator yielding every matching Team across all pages."""
        query = self._teams_query(ids, numbers, events, registered, programs,
                                   grades, countries, my_teams)
        return self._iter_items("/teams", query, per_page=per_page)

    def get_team(self, team_id):
        """GET /teams/{id} - a single Team, or raises VexEventsNotFoundError."""
        return self._request("/teams/%s" % team_id)

    def get_team_events(self, team_id, skus=None, seasons=None, start=None,
                         end=None, levels=None, page=None, per_page=None):
        """GET /teams/{id}/events - one page of Events a Team has attended."""
        query = {
            "sku[]": skus,
            "season[]": seasons,
            "start": start,
            "end": end,
            "level[]": levels,
        }
        return self._paginated_request(
            "/teams/%s/events" % team_id, query, page=page, per_page=per_page)

    def iter_team_events(self, team_id, skus=None, seasons=None, start=None,
                          end=None, levels=None, per_page=None):
        """GET /teams/{id}/events - generator over every Event the Team attended."""
        query = {
            "sku[]": skus,
            "season[]": seasons,
            "start": start,
            "end": end,
            "level[]": levels,
        }
        return self._iter_items("/teams/%s/events" % team_id, query, per_page=per_page)

    def get_team_matches(self, team_id, events=None, seasons=None, rounds=None,
                          instances=None, matchnums=None, page=None, per_page=None):
        """GET /teams/{id}/matches - one page of Matches a Team has played."""
        query = {
            "event[]": events,
            "season[]": seasons,
            "round[]": rounds,
            "instance[]": instances,
            "matchnum[]": matchnums,
        }
        return self._paginated_request(
            "/teams/%s/matches" % team_id, query, page=page, per_page=per_page)

    def iter_team_matches(self, team_id, events=None, seasons=None, rounds=None,
                           instances=None, matchnums=None, per_page=None):
        """GET /teams/{id}/matches - generator over every Match the Team played."""
        query = {
            "event[]": events,
            "season[]": seasons,
            "round[]": rounds,
            "instance[]": instances,
            "matchnum[]": matchnums,
        }
        return self._iter_items("/teams/%s/matches" % team_id, query, per_page=per_page)

    def get_team_rankings(self, team_id, events=None, ranks=None, seasons=None,
                           page=None, per_page=None):
        """GET /teams/{id}/rankings - one page of Rankings for a Team."""
        query = {"event[]": events, "rank[]": ranks, "season[]": seasons}
        return self._paginated_request(
            "/teams/%s/rankings" % team_id, query, page=page, per_page=per_page)

    def iter_team_rankings(self, team_id, events=None, ranks=None, seasons=None, per_page=None):
        """GET /teams/{id}/rankings - generator over every Ranking for a Team."""
        query = {"event[]": events, "rank[]": ranks, "season[]": seasons}
        return self._iter_items("/teams/%s/rankings" % team_id, query, per_page=per_page)

    def get_team_skills(self, team_id, events=None, types=None, seasons=None,
                         page=None, per_page=None):
        """GET /teams/{id}/skills - one page of Skills runs a Team has performed."""
        query = {"event[]": events, "type[]": types, "season[]": seasons}
        return self._paginated_request(
            "/teams/%s/skills" % team_id, query, page=page, per_page=per_page)

    def iter_team_skills(self, team_id, events=None, types=None, seasons=None, per_page=None):
        """GET /teams/{id}/skills - generator over every Skills run a Team performed."""
        query = {"event[]": events, "type[]": types, "season[]": seasons}
        return self._iter_items("/teams/%s/skills" % team_id, query, per_page=per_page)

    def get_team_awards(self, team_id, events=None, seasons=None, page=None, per_page=None):
        """GET /teams/{id}/awards - one page of Awards a Team has received."""
        query = {"event[]": events, "season[]": seasons}
        return self._paginated_request(
            "/teams/%s/awards" % team_id, query, page=page, per_page=per_page)

    def iter_team_awards(self, team_id, events=None, seasons=None, per_page=None):
        """GET /teams/{id}/awards - generator over every Award a Team received."""
        query = {"event[]": events, "season[]": seasons}
        return self._iter_items("/teams/%s/awards" % team_id, query, per_page=per_page)

    # -- Programs ------------------------------------------------------------

    def get_program(self, program_id):
        """GET /programs/{id} - a single Program, or raises VexEventsNotFoundError."""
        return self._request("/programs/%s" % program_id)

    def get_programs(self, ids=None, page=None, per_page=None):
        """GET /programs - one page of Programs matching the given filters."""
        query = {"id[]": ids}
        return self._paginated_request("/programs", query, page=page, per_page=per_page)

    def iter_programs(self, ids=None, per_page=None):
        """GET /programs - generator yielding every matching Program."""
        query = {"id[]": ids}
        return self._iter_items("/programs", query, per_page=per_page)

    # -- Seasons ------------------------------------------------------------

    def _seasons_query(self, ids=None, programs=None, teams=None, start=None,
                        end=None, active=None):
        return {
            "id[]": ids,
            "program[]": programs,
            "team[]": teams,
            "start": start,
            "end": end,
            "active": active,
        }

    def get_seasons(self, ids=None, programs=None, teams=None, start=None,
                     end=None, active=None, page=None, per_page=None):
        """GET /seasons - one page of Seasons matching the given filters."""
        query = self._seasons_query(ids, programs, teams, start, end, active)
        return self._paginated_request("/seasons", query, page=page, per_page=per_page)

    def iter_seasons(self, ids=None, programs=None, teams=None, start=None,
                      end=None, active=None, per_page=None):
        """GET /seasons - generator yielding every matching Season."""
        query = self._seasons_query(ids, programs, teams, start, end, active)
        return self._iter_items("/seasons", query, per_page=per_page)

    def get_season(self, season_id):
        """GET /seasons/{id} - a single Season, or raises VexEventsNotFoundError."""
        return self._request("/seasons/%s" % season_id)

    def get_season_events(self, season_id, skus=None, teams=None, start=None,
                           end=None, levels=None, page=None, per_page=None):
        """GET /seasons/{id}/events - one page of Events in a Season."""
        query = {
            "sku[]": skus,
            "team[]": teams,
            "start": start,
            "end": end,
            "level[]": levels,
        }
        return self._paginated_request(
            "/seasons/%s/events" % season_id, query, page=page, per_page=per_page)

    def iter_season_events(self, season_id, skus=None, teams=None, start=None,
                            end=None, levels=None, per_page=None):
        """GET /seasons/{id}/events - generator over every Event in a Season."""
        query = {
            "sku[]": skus,
            "team[]": teams,
            "start": start,
            "end": end,
            "level[]": levels,
        }
        return self._iter_items("/seasons/%s/events" % season_id, query, per_page=per_page)


__version__ = "0.1.0"

__all__ = [
    "VexEventsClient",
    "DEFAULT_BASE_URL",
    "VexEventsError",
    "VexEventsConnectionError",
    "VexEventsHTTPError",
    "VexEventsNotFoundError",
    "VexEventsAuthError",
    "EventType",
    "EventLevel",
    "Grade",
    "SkillType",
    "AllianceColor",
    "AwardDesignation",
    "AwardClassification",
    "MatchRound",
]

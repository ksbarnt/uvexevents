"""Handling network failures and API errors from uvexevents.

All errors raised by the client are subclasses of VexEventsError, so
`except VexEventsError` catches everything if you don't need to
distinguish cases.
"""

from uvexevents import (
    VexEventsClient,
    VexEventsError,
    VexEventsConnectionError,
    VexEventsNotFoundError,
    VexEventsAuthError,
    VexEventsHTTPError,
)

client = VexEventsClient(token="your-vex-events-api-token")

try:
    team = client.get_team(999999999)  # almost certainly doesn't exist
    print("Team:", team["number"])
except VexEventsNotFoundError:
    print("That team id doesn't exist.")
except VexEventsAuthError as exc:
    print("Auth problem - check your token:", exc)
except VexEventsConnectionError as exc:
    # No WiFi, DNS failure, TLS error, timeout, etc. - the request never
    # got a response from the server at all.
    print("Couldn't reach the API:", exc)
except VexEventsHTTPError as exc:
    # Any other 4xx/5xx not covered by a more specific subclass above.
    print("API returned an error: [%s] %s" % (exc.status, exc.message))
except VexEventsError as exc:
    # Catch-all, e.g. a malformed JSON response.
    print("Unexpected uvexevents error:", exc)

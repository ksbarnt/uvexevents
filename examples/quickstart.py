"""Basic usage of uvexevents: fetch and print a page of Events.

Run on a device already connected to the network (or on the MicroPython
Unix port with 'urequests' installed via mip). See wifi_esp32.py if you
need to bring up WiFi first.
"""

from uvexevents import VexEventsClient, EventLevel

API_TOKEN = "your-vex-events-api-token"

client = VexEventsClient(token=API_TOKEN)

# One page (default: page 1, 25 results) of World-level events in season 181.
page = client.get_events(seasons=[181], levels=[EventLevel.WORLD], per_page=10)

print("Page %d of %d (%d results total)" % (
    page["meta"]["current_page"], page["meta"]["last_page"], page["meta"]["total"]))

for event in page["data"]:
    print("%s | %s | %s -> %s" % (
        event["sku"], event["name"], event.get("start"), event.get("end")))

# Fetch one event's teams directly.
if page["data"]:
    event_id = page["data"][0]["id"]
    teams = client.get_event_teams(event_id, registered=True, per_page=5)
    print("\nFirst registered teams at %s:" % page["data"][0]["sku"])
    for team in teams["data"]:
        print(" -", team["number"], team.get("team_name"))

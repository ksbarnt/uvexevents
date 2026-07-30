"""Example: connect an ESP32/ESP8266 to WiFi, then query the VEX Events API.

Flash this alongside the uvexevents/ package (copy both to the board's
filesystem, e.g. with `mpremote cp -r uvexevents :` and
`mpremote cp examples/wifi_esp32.py :main.py`), fill in your SSID,
password and API token below, and run it.

Requires the 'urequests' library on the device:
    mpremote mip install urequests
"""

import time
import network

from uvexevents import VexEventsClient, VexEventsError

WIFI_SSID = "your-wifi-ssid"
WIFI_PASSWORD = "your-wifi-password"
API_TOKEN = "your-vex-events-api-token"


def connect_wifi(ssid, password, timeout_s=20):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting to WiFi:", ssid)
        wlan.connect(ssid, password)
        deadline = time.time() + timeout_s
        while not wlan.isconnected():
            if time.time() > deadline:
                raise RuntimeError("WiFi connection timed out")
            time.sleep(0.5)
    print("WiFi connected, IP:", wlan.ifconfig()[0])
    return wlan


def main():
    connect_wifi(WIFI_SSID, WIFI_PASSWORD)

    client = VexEventsClient(token=API_TOKEN)

    try:
        # Look up a specific event by SKU-derived id, then list its teams.
        page = client.get_events(skus=["RE-VRC-23-1234"], per_page=1)
        if not page["data"]:
            print("No event found for that SKU")
            return

        event = page["data"][0]
        print("Event:", event["name"], "(%s)" % event["sku"])

        teams_page = client.get_event_teams(event["id"], per_page=50)
        print("Teams (%d of %d):" % (
            len(teams_page["data"]), teams_page["meta"]["total"]))
        for team in teams_page["data"]:
            print(" -", team["number"], team.get("team_name", ""))

    except VexEventsError as exc:
        print("VEX Events API error:", exc)


main()

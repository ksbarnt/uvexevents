"""Two ways to consume paginated endpoints: manual pages vs. auto-iteration.

On memory-constrained boards, prefer the iter_* generators - they hold
only one page (default 25 items, tune with per_page) in RAM at a time
instead of accumulating a full result list.
"""

from uvexevents import VexEventsClient

API_TOKEN = "your-vex-events-api-token"
client = VexEventsClient(token=API_TOKEN)

TEAM_NUMBER_EVENT_ID = 12345  # replace with a real event id

# -- Manual: fetch page by page yourself, e.g. to show a "next page" UI ----
page_num = 1
page = client.get_event_skills(TEAM_NUMBER_EVENT_ID, page=page_num, per_page=25)
print("Skills runs, page %d/%d:" % (page["meta"]["current_page"], page["meta"]["last_page"]))
for run in page["data"]:
    print(" -", run["team"]["name"], run["type"], run["score"])

# -- Automatic: iterate every Skill run across all pages, one at a time ----
total = 0
for run in client.iter_event_skills(TEAM_NUMBER_EVENT_ID, per_page=50):
    total += 1
print("\nTotal skills runs at this event:", total)

# -- Filtering + iteration combined --
programming_runs = client.iter_event_skills(TEAM_NUMBER_EVENT_ID, types=["programming"])
best = None
for run in programming_runs:
    if best is None or run["score"] > best["score"]:
        best = run
if best:
    print("Top programming skills score:", best["score"], "by team", best["team"]["name"])

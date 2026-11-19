"""Export yesterday's calls (UTC) to calls.csv: id, date, type, status, sentiment, duration. Frontline login."""
import csv
import sys
from datetime import datetime, time, timedelta, timezone

from _common import client_from_env

today = datetime.combine(datetime.now(timezone.utc).date(), time(0), tzinfo=timezone.utc)
start, end = today - timedelta(days=1), today - timedelta(seconds=1)
out = sys.argv[1] if len(sys.argv) > 1 else "calls.csv"
fields = ["id", "location_id", "call_date", "call_type", "status", "sentiment", "sentiment_score", "duration"]

with client_from_env() as client, open(out, "w", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    n = 0
    for call in client.intelligence.iter_calls(date_from=start, date_to=end):
        writer.writerow(call)
        n += 1
print(f"{n} calls written to {out}")

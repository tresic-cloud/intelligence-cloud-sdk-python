"""A dependency-free First Alert webhook receiver (standard library plus this SDK).

    IC_ALERT_WEBHOOK_TOKEN=<32+ random characters> IC_DATA_EMAIL=... IC_DATA_PASSWORD=... \
        python alert_webhook_receiver.py [port]

Make a token with: python -c "import secrets; print(secrets.token_urlsafe(32))"

Register https://<your host>/ic/alerts/<token> as the location's First Alert webhook (behind TLS),
for example with admin.intelligence.set_first_alert_webhook(location_id, url).
The receiver checks the path token in constant time, reads only the alert id from the request,
answers 204 at once and drops repeat deliveries of the same alert. A worker thread then fetches the
alert and its call with the frontline integration user (a member of Manager Alerts).
Pass --self-test to post a sample delivery to itself, without fetching, and exit.
"""
import hmac
import json
import os
import queue
import secrets
import sys
import threading
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from intelligence_cloud import Deduplicator

SELF_TEST = "--self-test" in sys.argv
TOKEN = os.environ.get("IC_ALERT_WEBHOOK_TOKEN") or (secrets.token_urlsafe(32) if SELF_TEST else "")
if len(TOKEN) < 32:
    raise SystemExit("Set IC_ALERT_WEBHOOK_TOKEN to at least 32 random characters: "
                     'python -c "import secrets; print(secrets.token_urlsafe(32))"')
PORT = int(next((a for a in sys.argv[1:] if a.isdigit()), "8081"))
MAX_BODY = 65536
alert_ids: "queue.Queue[str]" = queue.Queue()
dedup = Deduplicator()


def alert_id_from(body: bytes) -> Optional[str]:
    """The alert id from a First Alert delivery, or None. Reads nothing else from the request."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    nested = data.get("alert") if isinstance(data.get("alert"), dict) else {}
    for value in (data.get("alert_id"), nested.get("id"), data.get("id")):
        if isinstance(value, str):
            try:
                return str(uuid.UUID(value.strip()))
            except ValueError:
                continue
    return None


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not hmac.compare_digest(self.path.encode(), f"/ic/alerts/{TOKEN}".encode()):
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length") or 0)
        alert_id = alert_id_from(self.rfile.read(length)) if 0 < length <= MAX_BODY else None
        if alert_id is None:
            self.send_response(400)
            self.end_headers()
            return
        if not dedup.is_duplicate(alert_id):
            alert_ids.put(alert_id)
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):  # don't log request lines: the path holds the secret token
        pass


def worker(fetch: bool):
    client = None
    if fetch:
        from _common import client_from_env
        client = client_from_env("data")
    while True:
        alert_id = alert_ids.get()
        if client is not None:
            alert = client.intelligence.get_alert(alert_id, with_call=True)
            if alert is None:
                print(f"alert {alert_id} is not visible to this login")
            else:
                # Hand ids to your paging, chat or ticketing tool; never log the summary or numbers.
                print(f"alert {alert_id} rules={','.join(alert.get('keywords') or [])} call={alert.get('call_id')}")
        else:
            print(f"alert {alert_id} received")
        alert_ids.task_done()


if __name__ == "__main__":
    self_test = SELF_TEST
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=worker, args=(not self_test,), daemon=True).start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if self_test:
        url = f"http://127.0.0.1:{PORT}/ic/alerts/{TOKEN}"
        sample = json.dumps({"alert_id": "cccccccc-dddd-4eee-8fff-000000000001"}).encode()  # only the id is read
        for _ in range(2):  # the second delivery is a duplicate and is dropped
            req = urllib.request.Request(url, data=sample, method="POST",
                                         headers={"Content-Type": "application/json"})
            print("delivery answered", urllib.request.urlopen(req).status)
        alert_ids.join()
        server.shutdown()
    else:
        print(f"listening on 127.0.0.1:{PORT}")
        threading.Event().wait()

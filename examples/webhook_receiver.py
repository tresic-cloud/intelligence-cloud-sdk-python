"""A dependency-free After Call webhook receiver (standard library plus this SDK).

    IC_WEBHOOK_TOKEN=<32+ random characters> IC_DATA_EMAIL=... IC_DATA_PASSWORD=... \
        python webhook_receiver.py [port]

Make a token with: python -c "import secrets; print(secrets.token_urlsafe(32))"

Register https://<your host>/ic/after-call/<token> as the location's After Call webhook (behind TLS).

- The path token is compared in constant time; a wrong token gets 404.
- Bodies over 256 KB get 413; a body that is not JSON, or a malformed After Call event, gets 400.
  Event types this SDK doesn't handle get 204 and are ignored.
- Each event's call id is written to a persistent queue (SQLite, keyed on call.id) BEFORE the
  delivery is acknowledged, so nothing is lost on restart and repeats collapse into one entry.
- A worker reads each queued call with the frontline integration user (the event is only a
  notification) and then upserts your copy on call.id. A 404 means drop it.

Pass --self-test to post the sample event to itself twice, without reading the API, and exit.
"""
import hmac
import json
import os
import secrets
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from intelligence_cloud import (
    MAX_EVENT_BYTES,
    AfterCallEvent,
    NotFoundError,
    PayloadTooLargeError,
    WebhookPayloadError,
    parse_after_call_event,
)

SELF_TEST = "--self-test" in sys.argv
TOKEN = os.environ.get("IC_WEBHOOK_TOKEN") or (secrets.token_urlsafe(32) if SELF_TEST else "")
if len(TOKEN) < 32:
    raise SystemExit("Set IC_WEBHOOK_TOKEN to at least 32 random characters: "
                     'python -c "import secrets; print(secrets.token_urlsafe(32))"')
PORT = int(next((a for a in sys.argv[1:] if a.isdigit()), "8080"))
QUEUE_PATH = os.environ.get("IC_QUEUE_PATH") or (
    os.path.join(tempfile.mkdtemp(), "queue.db") if SELF_TEST else "ic-after-call-queue.db")
SAMPLE = Path(__file__).with_name("after-call-sample.json")


class CallQueue:
    """A persistent queue of call ids. A repeat delivery of a queued call id is one entry."""

    def __init__(self, path: str):
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("CREATE TABLE IF NOT EXISTS calls (call_id TEXT PRIMARY KEY, received REAL, done INTEGER DEFAULT 0)")
        self._lock = threading.Lock()

    def put(self, call_id: str) -> None:
        with self._lock:  # a repeat after processing re-opens the entry: it may carry newer data
            self._db.execute("INSERT INTO calls (call_id, received) VALUES (?, ?) "
                             "ON CONFLICT(call_id) DO UPDATE SET done = 0, received = excluded.received",
                             (call_id, time.time()))

    def next(self):
        with self._lock:
            row = self._db.execute("SELECT call_id FROM calls WHERE done = 0 ORDER BY received LIMIT 1").fetchone()
        return row[0] if row else None

    def done(self, call_id: str) -> None:
        with self._lock:
            self._db.execute("UPDATE calls SET done = 1 WHERE call_id = ?", (call_id,))

    def pending(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM calls WHERE done = 0").fetchone()[0]


calls = CallQueue(QUEUE_PATH)


class Handler(BaseHTTPRequestHandler):
    def _answer(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        if not hmac.compare_digest(self.path.encode(), f"/ic/after-call/{TOKEN}".encode()):
            return self._answer(404)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._answer(400)
        if length > MAX_EVENT_BYTES:
            return self._answer(413)
        try:
            event = parse_after_call_event(self.rfile.read(length))
        except PayloadTooLargeError:
            return self._answer(413)
        except WebhookPayloadError:
            return self._answer(400)
        if isinstance(event, AfterCallEvent):
            calls.put(event.call.id)  # stored before the acknowledgement
        return self._answer(204)

    def log_message(self, *args):  # don't log request lines: the path holds the secret token
        pass


def worker(fetch: bool) -> None:
    client = None
    if fetch:
        from _common import client_from_env
        client = client_from_env("data")
    while True:
        call_id = calls.next()
        if call_id is None:
            time.sleep(0.2)
            continue
        if client is not None:
            try:
                call = client.intelligence.get_call(call_id)
            except NotFoundError:
                print(f"call {call_id} is not visible to this login; dropped")
            else:
                # Upsert your copy on call_id here. Never log the summary, names or numbers.
                print(f"call {call_id} read ({len(call)} fields)")
        else:
            print(f"call {call_id} queued")
        calls.done(call_id)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=worker, args=(not SELF_TEST,), daemon=True).start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if SELF_TEST:
        url = f"http://127.0.0.1:{PORT}/ic/after-call/{TOKEN}"
        body = SAMPLE.read_bytes()
        for _ in range(2):  # the second delivery is a repeat of the same call id: one queue entry
            req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
            print("delivery answered", urllib.request.urlopen(req).status)
        while calls.pending():
            time.sleep(0.1)
        server.shutdown()
    else:
        print(f"listening on 127.0.0.1:{PORT}")
        threading.Event().wait()

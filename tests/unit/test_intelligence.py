"""Conversation intelligence helpers and the webhook receiver."""
from __future__ import annotations

import json

import httpx
import pytest

import intelligence_cloud as ic

LID = "0193b6c2-6b29-7a51-b0e4-1c8f3d5e7a02"
CALL = "0193b6d0-1e2f-7a3b-8c4d-5e6f7a8b9c01"
ALERT = "7b1e2c3d-4f5a-4b6c-8d9e-0f1a2b3c4d5e"
CONN = "4b7e9d2c-1a3f-4e8b-9c6d-2f5a8e1b3c70"


def server(role="frontline_user", log=None):
    def h(r):
        p = r.url.path.replace("/api/v1", "")
        if log is not None:
            log.append((r.method, p, dict(r.url.params), json.loads(r.content) if r.content else None))
        if p == "/auth/login":
            return httpx.Response(200, json={"access_token": "A", "refresh_token": "R", "token_type": "Bearer",
                                             "expires_in": 899, "user": {}})
        if p == "/me":
            return httpx.Response(200, json={"data": {"role": role, "id": "u"}})
        if p == "/calls":
            return httpx.Response(200, json={"data": {"summary": {"total_calls": 1}, "calls": [{"id": CALL}]},
                                             "meta": {"has_more": False}})
        if p == f"/calls/{CALL}":
            return httpx.Response(200, json={"data": {"id": CALL, "summary": "s", "vcon": {
                "unexpected_id": "doc-1", "unexpected_count": 2, "recording_mime_type": "audio/wav",
                "recording_url": "https://media.example.com/r.wav?sig=SIGNED",
                "recording_url_expires_at": "2026-11-02T18:46:12.5Z"}}})
        if p == f"/calls/{ALERT}":
            return httpx.Response(200, json={"data": {"id": ALERT, "vcon": {"unexpected_id": "doc-2", "recording_url": None}}})
        if p == f"/calls/{CALL}/transcript":
            return httpx.Response(200, json={"data": {"transcript": [{"time": 0.5, "speaker": "Speaker 1",
                                                                      "name": "A", "text": "hi", "unexpected_field": 0.9}]}})
        if p == "/alerts":
            return httpx.Response(200, json={"data": {"summary": {"total": 1}, "alerts": [
                {"id": ALERT, "call_id": CALL, "keywords": ["Upset Customer"]}]}, "meta": {"has_more": False}})
        if p.endswith("/after-call/automation") and r.method == "GET":
            return httpx.Response(200, json={"data": None})
        if p.endswith("/after-call/automation") and r.method == "PUT":
            return httpx.Response(200, json={"data": dict(json.loads(r.content), id="w", location_id=LID)})
        if p.endswith("/after-call/automation/test"):
            return httpx.Response(200, json={"data": {"success": False, "http_status": 500, "response_time_ms": 12,
                                                      "error": "upstream detail: 192.0.2.10 refused"}})
        if p.endswith("/first-alert/config") and r.method == "GET":
            return httpx.Response(200, json={"data": {"webhook_url": "https://hooks.example.com/fa", "connector_mappings": [
                {"id": "m", "connector_id": CONN, "connector_name": "x", "monitored_numbers": ["2101"]}]}})
        if p.endswith("/first-alert/config") and r.method == "PUT":
            return httpx.Response(200, json={"data": json.loads(r.content)})
        if p.endswith("/test-webhook"):
            return httpx.Response(200, json={"data": {"success": True, "status_code": 204, "message": "ok"}})
        return httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": p}})
    return h


def client(role="frontline_user", log=None):
    return ic.Client(email="i@example.com", password="pw", transport=httpx.MockTransport(server(role, log)),
                     sleep=lambda s: None)


def test_admin_login_gets_clear_error():
    c = client("reseller_admin")
    with pytest.raises(ic.FrontlineRequiredError) as e:
        c.intelligence.search_calls()
    assert "reseller_admin" in str(e.value)


def test_search_calls_maps_phone_and_text_to_search():
    log = []
    c = client(log=log)
    page = c.intelligence.search_calls(phone="(555) 555-0142", location_ids=[LID], status="completed")
    assert page.items == [{"id": CALL}] and page.total == 1
    q = [x for x in log if x[1] == "/calls"][-1][2]
    assert q == {"search": "(555) 555-0142", "location_id": LID, "status": "completed"}
    with pytest.raises(ic.InvalidRequestError):
        c.intelligence.search_calls(phone="5550142", text="refund")
    with pytest.raises(ic.InvalidRequestError):
        c.intelligence.search_calls(text="a")
    assert c.intelligence.get_call(CALL)["id"] == CALL
    seg = c.intelligence.get_transcript(CALL)
    assert seg == [{"time": 0.5, "speaker": "Speaker 1", "name": "A", "text": "hi"}]


def test_whoami_checked_once():
    log = []
    c = client(log=log)
    c.intelligence.search_calls()
    c.intelligence.search_calls()
    assert sum(1 for x in log if x[1] == "/me") == 1


def test_search_alerts_and_get_alert():
    log = []
    c = client(log=log)
    c.intelligence.search_alerts(alert_name="Upset Customer", numbers=["+1 555-555-0142"], text="refund")
    q = [x for x in log if x[1] == "/alerts"][-1][2]
    assert q == {"keyword": "Upset Customer", "numbers": "5555550142", "search": "refund"}
    a = c.intelligence.get_alert(ALERT.upper(), with_call=True)
    assert a["id"] == ALERT and a["call"]["id"] == CALL
    assert [x for x in log if x[1] == "/alerts"][-1][2]["search"] == ALERT


def test_after_call_webhook_config():
    log = []
    c = client("reseller_admin", log)
    assert c.intelligence.get_after_call_webhook(LID) is None
    out = c.intelligence.set_after_call_webhook(LID, "https://hooks.example.com/ic/abc123", enabled=False)
    assert out["enabled"] is False
    res = c.intelligence.test_after_call_webhook(LID)
    assert res == ic.WebhookTestResult(success=False, http_status=500)
    with pytest.raises(ic.InvalidRequestError):
        c.intelligence.set_after_call_webhook(LID, "http://hooks.example.com/x")


def test_first_alert_webhook_keeps_numbers():
    log = []
    c = client("reseller_admin", log)
    assert c.intelligence.get_first_alert_webhook(LID) == "https://hooks.example.com/fa"
    c.intelligence.set_first_alert_webhook(LID, "https://hooks.example.com/fa2")
    put = [x for x in log if x[0] == "PUT"][-1][3]
    assert put == {"webhook_url": "https://hooks.example.com/fa2",
                   "connector_mappings": [{"connector_id": CONN, "monitored_numbers": ["2101"]}]}
    assert c.intelligence.test_first_alert_webhook(LID) == ic.WebhookTestResult(True, 204)


# ------------------------------------------------------------------ receiver

EVENT = {
    "version": "1.0", "type": "end_of_call_summary", "is_test": False,
    "location_id": LID, "timestamp": "2026-11-02T16:46:12Z",
    "call": {"id": CALL, "caller_name": "Morgan Diaz", "caller_number": "+15555550142", "call_type": "inbound",
             "duration_seconds": 284, "call_date": "2026-11-02", "platform": "netsapiens"},
    "summary": {"text": "Car not ready.", "sentiment": "negative", "subject": "hidden"},
    "location": {"id": LID, "company_id": "0193b6c2-5a11-7c3e-8f20-6d4b9e1c2a77", "connector_id": CONN},
    "extra_unexpected": {"x": 1},
}


def test_parse_after_call_event():
    ev = ic.parse_after_call_event(json.dumps(EVENT).encode())
    assert ev.call.id == CALL and ev.call.duration_seconds == 284 and ev.call.call_date.isoformat() == "2026-11-02"
    assert ev.summary.text == "Car not ready." and ev.location.connector_id == CONN
    assert ev.timestamp.isoformat() == "2026-11-02T16:46:12+00:00"
    assert "extra_unexpected" not in ev.raw and "subject" not in ev.raw["summary"]


@pytest.mark.parametrize("mutate", [
    lambda e: e.pop("call"),
    lambda e: e["call"].update(duration_seconds="284"),
    lambda e: e["call"].update(call_date="yesterday"),
])
def test_parse_rejects_bad_events(mutate):
    bad = json.loads(json.dumps(EVENT))
    mutate(bad)
    with pytest.raises(ic.WebhookPayloadError):
        ic.parse_after_call_event(bad)


def test_parse_rejects_non_json():
    with pytest.raises(ic.WebhookPayloadError):
        ic.parse_after_call_event(b"<html>")


def test_deduplicator_lru():
    d = ic.Deduplicator(max_size=2)
    ev = ic.parse_after_call_event(EVENT)
    assert not d.is_duplicate(ev)
    assert d.is_duplicate(ev)
    assert not d.is_duplicate("b") and not d.is_duplicate("c")
    assert not d.is_duplicate(ev)  # evicted


def test_dedup_custom_store():
    class Store:
        def __init__(self):
            self.keys = set()

        def add(self, key):
            if key in self.keys:
                return False
            self.keys.add(key)
            return True
    d = ic.Deduplicator(store=Store())
    assert not d.is_duplicate("x") and d.is_duplicate("x")


def test_get_recording_url_returns_only_link_and_expiry():
    c = client()
    link = c.intelligence.get_recording_url(CALL)
    assert link.url == "https://media.example.com/r.wav?sig=SIGNED"
    assert link.expires_at.isoformat() == "2026-11-02T18:46:12.500000+00:00"
    assert "SIGNED" not in repr(link)
    assert set(vars(link)) == {"url", "expires_at"}
    assert c.intelligence.get_recording_url(ALERT) is None


def test_call_detail_never_carries_the_rest_of_vcon():
    from intelligence_cloud import _spec
    body = {"data": {"id": CALL, "vcon": {"unexpected_id": "doc-1", "unexpected_count": 2, "recording_url": "u",
                                          "recording_url_expires_at": "t"}}}
    out = _spec.project_response("getCall", 200, body)
    assert out["data"].get("vcon", {}).keys() <= {"recording_url", "recording_url_expires_at"}
    detail = client().intelligence.get_call(CALL)
    assert "unexpected_id" not in json.dumps(detail) and "unexpected_count" not in json.dumps(detail.get("vcon", {}))

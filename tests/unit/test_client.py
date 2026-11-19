"""Core client: auth, retries, errors, projection, filters, paging, idempotency, connector waits."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

import httpx
import pytest

import intelligence_cloud as ic
from intelligence_cloud import _spec

CID = "0193b6c2-5a11-7c3e-8f20-6d4b9e1c2a77"
LID = "0193b6c2-6b29-7a51-b0e4-1c8f3d5e7a02"
UID = "0193b6c2-7c44-7d12-a3f9-8e2b6c1d4f55"
CONN = "4b7e9d2c-1a3f-4e8b-9c6d-2f5a8e1b3c70"


def token_body(n: int):
    return {"access_token": f"A{n}", "refresh_token": f"R{n}", "token_type": "Bearer", "expires_in": 899,
            "user": {"id": UID, "role": "frontline_user"}}


class Scripted:
    """A transport that answers from a list of handlers and records every request."""

    def __init__(self, handler):
        self.handler = handler
        self.requests = []
        self.lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            self.requests.append(request)
        return self.handler(request)

    def paths(self):
        return [(r.method, r.url.path.replace("/api/v1", "")) for r in self.requests]


def make(handler, **kw):
    t = Scripted(handler)
    sleeps = []
    kw.setdefault("sleep", sleeps.append)
    c = ic.Client(email="integration@example.com", password="pw", transport=httpx.MockTransport(t), **kw)
    return c, t, sleeps


def login_ok(request):
    return httpx.Response(200, json=token_body(1))


# ------------------------------------------------------------------ auth

def test_logs_in_once_and_sends_bearer():
    def h(r):
        if r.url.path.endswith("/auth/login"):
            return login_ok(r)
        assert r.headers["Authorization"] == "Bearer A1"
        return httpx.Response(200, json={"data": {"id": UID, "role": "frontline_user"}})
    c, t, _ = make(h)
    c.account.get_me()
    c.account.get_me()
    assert [p for p in t.paths() if p[1] == "/auth/login"] == [("POST", "/auth/login")]
    body = json.loads(t.requests[0].content)
    assert body == {"email": "integration@example.com", "password": "pw"}


def test_refresh_rotates_and_never_reuses_refresh_token():
    state = {"n": 1, "refresh_bodies": []}

    def h(r):
        p = r.url.path
        if p.endswith("/auth/login"):
            return login_ok(r)
        if p.endswith("/auth/refresh"):
            state["refresh_bodies"].append(json.loads(r.content)["refresh_token"])
            state["n"] += 1
            return httpx.Response(200, json=token_body(state["n"]))
        if r.headers["Authorization"] != f"Bearer A{state['n']}":
            return httpx.Response(401, json={"statusCode": 401, "message": "Unauthorized"})
        return httpx.Response(200, json={"data": {"id": UID}})
    store = ic.MemoryTokenStore()
    c, t, _ = make(h, token_store=store)
    c.account.get_me()
    state["n"] = 5  # the server no longer accepts A1: the next call gets 401 and refreshes
    c.account.get_me()
    assert state["refresh_bodies"] == ["R1"]
    assert store.get().refresh_token == "R6"
    # the next 401 must use R6, never R1 again
    state["n"] = 10
    c.account.get_me()
    assert state["refresh_bodies"] == ["R1", "R6"]


def test_concurrent_401_triggers_single_refresh():
    state = {"valid": "A1", "refreshes": 0}
    gate = threading.Barrier(4)

    def h(r):
        p = r.url.path
        if p.endswith("/auth/login"):
            return login_ok(r)
        if p.endswith("/auth/refresh"):
            state["refreshes"] += 1
            state["valid"] = "A2"
            return httpx.Response(200, json=token_body(2))
        if r.headers["Authorization"] != f"Bearer {state['valid']}":
            return httpx.Response(401, json={"error": {"code": "unauthorized", "message": "expired"}})
        return httpx.Response(200, json={"data": {}})
    c, t, _ = make(h)
    c.login()
    state["valid"] = "A-expired"
    errors = []

    def worker():
        try:
            gate.wait()
            c.account.get_me()
        except Exception as exc:  # pragma: no cover
            errors.append(exc)
    threads = [threading.Thread(target=worker) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert not errors
    assert state["refreshes"] == 1


def test_refresh_failure_falls_back_to_login():
    state = {"logins": 0}

    def h(r):
        p = r.url.path
        if p.endswith("/auth/login"):
            state["logins"] += 1
            return httpx.Response(200, json=token_body(state["logins"] * 10))
        if p.endswith("/auth/refresh"):
            return httpx.Response(401, json={"error": {"code": "renewal_replayed", "message": "no"}})
        if r.headers["Authorization"] == "Bearer A10":
            return httpx.Response(401, json={"statusCode": 401, "message": "Unauthorized"})
        return httpx.Response(200, json={"data": {}})
    c, _, _ = make(h)
    c.account.get_me()
    assert state["logins"] == 2


def test_expired_token_is_renewed_before_the_call():
    seen = []

    def h(r):
        p = r.url.path
        if p.endswith("/auth/refresh"):
            seen.append("refresh")
            return httpx.Response(200, json=token_body(2))
        seen.append(r.headers.get("Authorization"))
        return httpx.Response(200, json={"data": {}})
    store = ic.MemoryTokenStore(ic.Tokens("A1", "R1", expires_at=1.0))
    c, _, _ = make(h, token_store=store)
    c.account.get_me()
    assert seen == ["refresh", "Bearer A2"]


def test_mfa_required():
    c, _, _ = make(lambda r: httpx.Response(200, json={"status": "mfa_required"}))
    with pytest.raises(ic.MfaRequiredError) as e:
        c.account.get_me()
    assert "API keys arrive in December 2026" in str(e.value)


def test_login_rate_limit_waits_60s_once():
    state = {"n": 0}

    def h(r):
        if r.url.path.endswith("/auth/login"):
            state["n"] += 1
            if state["n"] == 1:
                return httpx.Response(429, json={"error": {"code": "rate_limited", "message": "slow down"}})
            return login_ok(r)
        return httpx.Response(200, json={"data": {}})
    c, _, sleeps = make(h)
    c.account.get_me()
    assert sleeps == [60.0]


def test_logout_only_when_asked():
    def h(r):
        if r.url.path.endswith("/auth/login"):
            return login_ok(r)
        return httpx.Response(200, json={"message": "ok"} if r.url.path.endswith("logout") else {"data": {}})
    c, t, _ = make(h)
    c.account.get_me()
    c.close()
    assert ("POST", "/auth/logout") not in t.paths()
    c2, t2, _ = make(h)
    c2.login()
    c2.logout()
    assert ("POST", "/auth/logout") in t2.paths()


def test_secrets_not_in_repr():
    c, _, _ = make(login_ok)
    assert "pw" not in repr(c)
    assert "A1" not in repr(ic.Tokens("A1", "R1", 0))


# ------------------------------------------------------------------ retries

def test_429_backoff_honours_retry_after():
    state = {"n": 0}

    def h(r):
        if r.url.path.endswith("/auth/login"):
            return login_ok(r)
        state["n"] += 1
        if state["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={"error": {"message": "slow"}})
        return httpx.Response(200, json={"data": {}})
    c, _, sleeps = make(h)
    c.account.get_me()
    assert sleeps == [2.0, 2.0]


def test_retries_stop_after_three():
    def h(r):
        if r.url.path.endswith("/auth/login"):
            return login_ok(r)
        return httpx.Response(503, json={"error": {"code": "UNAVAILABLE", "message": "busy"}})
    c, t, sleeps = make(h)
    with pytest.raises(ic.ApiError) as e:
        c.account.get_me()
    assert e.value.status == 503
    assert len(sleeps) == 3
    assert all(0 < s <= 12 for s in sleeps)


def test_5xx_not_retried_on_plain_create():
    def h(r):
        if r.url.path.endswith("/auth/login"):
            return login_ok(r)
        return httpx.Response(502, json={"error": {"message": "bad gateway"}})
    c, t, sleeps = make(h)
    with pytest.raises(ic.ApiError):
        c.groups.create_user_group(LID, {"group_name": "Manager Alerts"})
    assert sleeps == []


def test_rate_limit_error_after_retries():
    def h(r):
        if r.url.path.endswith("/auth/login"):
            return login_ok(r)
        return httpx.Response(429, headers={"Retry-After": "1"}, json={"error": {"message": "slow"}})
    c, _, _ = make(h)
    with pytest.raises(ic.RateLimitError) as e:
        c.account.get_me()
    assert e.value.retry_after == 1.0


# ------------------------------------------------------------------ errors

@pytest.mark.parametrize("status,body,cls,code,msg", [
    (422, {"error": {"code": "VALIDATION_ERROR", "message": "Invalid sentiment", "request_id": "r1"}},
     ic.ValidationError, "VALIDATION_ERROR", "Invalid sentiment"),
    (400, {"error": {"type": "invalid_parameter", "message": "bad status"}}, ic.ValidationError,
     "invalid_parameter", "bad status"),
    (401, {"statusCode": 401, "message": "Unauthorized"}, ic.AuthError, None, "Unauthorized"),
    (400, {"error": "Idempotency-Key header is required"}, ic.ValidationError, None,
     "Idempotency-Key header is required"),
    (404, {"error": {"code": "NOT_FOUND", "message": "Company not found"}}, ic.NotFoundError, "NOT_FOUND",
     "Company not found"),
    (409, {"error": {"code": "CONFLICT", "message": "Company is already inactive"}}, ic.ConflictError,
     "CONFLICT", "Company is already inactive"),
])
def test_error_shapes_normalised(status, body, cls, code, msg):
    def h(r):
        if r.url.path.endswith("/auth/login"):
            return login_ok(r)
        return httpx.Response(status, json=body)
    c, _, _ = make(h)
    with pytest.raises(cls) as e:
        c.companies.get_company(CID)
    assert e.value.status == status and e.value.code == code and e.value.message == msg
    if cls is ic.NotFoundError:
        assert "outside what this login can see" in str(e.value)


def test_non_json_404():
    def h(r):
        if r.url.path.endswith("/auth/login"):
            return login_ok(r)
        return httpx.Response(404, text="<html>nope</html>", headers={"content-type": "text/html"})
    c, _, _ = make(h)
    with pytest.raises(ic.NotFoundError):
        c.companies.get_company(CID)


def test_extension_conflict_text_replaced():
    server_text = "Conflict: 2002 and 2008 are taken (example detail the SDK must not pass on)"

    def h(r):
        if r.url.path.endswith("/auth/login"):
            return login_ok(r)
        return httpx.Response(409, json={"error": {"code": "CONFLICT", "message": server_text}})
    c, _, _ = make(h)
    with pytest.raises(ic.ConflictError) as e:
        c.users.set_user_number_mappings(CID, UID, {"mappings": [
            {"connector_id": CONN, "monitored_numbers": ["2001", "2002", "2008"]}]})
    assert e.value.message == "Extension is already monitored at another location."
    assert e.value.extensions == ["2002", "2008"]
    assert "example detail" not in str(e.value)
    with pytest.raises(ic.ConflictError) as e2:
        c.after_call_settings.update_user_after_call_settings(LID, UID, {"connector_mappings": []})
    assert "example detail" not in str(e2.value) and e2.value.extensions == []


@pytest.mark.parametrize("call", [
    lambda c: c.connectors.test_connector(LID, {"type": "netsapiens", "config": {
        "api_url": "https://pbx.example.com/ns-api/v2", "domain": "d", "api_key": "k"}}),
    lambda c: c.first_alert.test_first_alert_webhook(LID, {"url": "https://example.com/h"}),
    lambda c: c.webhooks.test_after_call_webhook(LID),
])
def test_test_endpoints_never_surface_server_text(call):
    def h(r):
        if r.url.path.endswith("/auth/login"):
            return login_ok(r)
        return httpx.Response(422, json={"error": {"code": "X", "message": "upstream detail: 192.0.2.10 refused"}})
    c, _, _ = make(h)
    with pytest.raises(ic.ApiError) as e:
        call(c)
    assert "192.0.2.10" not in str(e.value) and "upstream detail" not in str(e.value)


def test_test_endpoint_success_drops_error_text():
    def h(r):
        if r.url.path.endswith("/auth/login"):
            return login_ok(r)
        return httpx.Response(200, json={"data": {"success": False, "error": "upstream detail: 192.0.2.10 refused"}})
    c, _, _ = make(h)
    out = c.connectors.test_connector(LID, {"type": "netsapiens", "config": {
        "api_url": "https://pbx.example.com/ns-api/v2", "domain": "d", "api_key": "k"}})
    assert out == {"data": {"success": False}}


# ------------------------------------------------------------------ projection

def test_projection_strips_unlisted_fields():
    def h(r):
        p = r.url.path
        if p.endswith("/auth/login"):
            return login_ok(r)
        if p.endswith("/me"):
            return httpx.Response(200, json={"data": {"id": UID, "role": "frontline_user",
                                                      "unexpected_field": "redacted", "unexpected_flag": False}})
        if "/connectors/" in p:
            return httpx.Response(200, json={"data": {"id": CONN, "status": "active", "unexpected_ref": "s",
                                                      "config": {"api_url": "https://pbx.example.com/ns-api/v2",
                                                                 "domain": "d", "unexpected_field": "redacted"}}})
        if p.endswith("/users"):
            return httpx.Response(201, json={"data": {"type": "company_user", "attributes": {
                "id": UID, "email": "sam@example.com", "external_id": "pending:x"}},
                "meta": {"invitation_link": "https://app.example.com/accept?t=SECRET"}})
        if "/calls/" in p:
            return httpx.Response(200, json={"data": {"id": UID, "unexpected_field": 0.9, "unexpected_object": {"unexpected_id": "x"},
                                                      "analysis": {"sentiment": {"overall": "negative", "unexpected_field": 0.8}}}})
        return httpx.Response(404, json={})
    c, _, _ = make(h)
    me = c.account.get_me()["data"]
    assert me == {"id": UID, "role": "frontline_user"}
    conn = c.connectors.get_connector(LID, CONN)["data"]
    assert "unexpected_field" not in conn["config"] and "unexpected_ref" not in conn
    created = c.users.create_company_user(CID, {"email": "sam@example.com", "first_name": "Sam",
                                                "last_name": "Ortiz", "role": "customer_admin"})
    assert "meta" not in created and "SECRET" not in json.dumps(created)
    assert "external_id" not in created["data"]["attributes"]
    call = c.calls.get_call(UID)["data"]
    assert call == {"id": UID, "analysis": {"sentiment": {"overall": "negative"}}}


def test_projection_keeps_oneof_trigger_config():
    rule = {"data": {"type": "first_alert_rule", "attributes": {"id": UID, "triggers": [
        {"id": "t", "trigger_type": "keyword_match", "config": {"keywords": ["cancel"], "match_logic": "any"}},
        {"id": "u", "trigger_type": "sentiment", "config": {"operator": "lt", "threshold": -40}}]}}}
    out = _spec.project_response("getAlertRule", 200, rule)
    assert out == rule


# ------------------------------------------------------------------ filters

def no_network(r):  # pragma: no cover - must never be reached
    raise AssertionError(f"request sent: {r.url}")


def test_unknown_filter_raises_before_sending():
    c, t, _ = make(no_network)
    with pytest.raises(TypeError):
        c.calls.list_calls(direction="inbound")  # type: ignore[call-arg]
    with pytest.raises(ic.InvalidRequestError):
        _spec.encode_query("listCalls", {"direction": "inbound"})
    assert t.requests == []


def test_unknown_body_field_raises_before_sending():
    c, t, _ = make(no_network)
    with pytest.raises(ic.InvalidRequestError):
        c.locations.create_location(CID, {"location_name": "Main", "street": "1", "city": "c", "state": "s",
                                          "country": "US", "zipcode": "1", "vertical_id": CID,
                                          "default_rule_pack": True})
    with pytest.raises(ic.InvalidRequestError):
        c.groups.create_user_group(LID, {})
    assert t.requests == []


@pytest.mark.parametrize("value", ["2026-11-01", "2026-11-01T00:00:00", "yesterday",
                                   datetime(2026, 11, 1).date(), datetime(2026, 11, 1)])
def test_date_only_or_offsetless_dates_rejected(value):
    c, t, _ = make(no_network)
    with pytest.raises(ic.InvalidRequestError):
        c.calls.list_calls(date_from=value)
    assert t.requests == []


def test_dates_sent_as_full_utc():
    seen = {}

    def h(r):
        if r.url.path.endswith("/auth/login"):
            return login_ok(r)
        seen.update(dict(r.url.params))
        return httpx.Response(200, json={"data": {"summary": {}, "calls": []}, "meta": {"has_more": False}})
    c, _, _ = make(h)
    c.calls.list_calls(date_from=datetime(2026, 11, 1, 6, 0, tzinfo=timezone(timedelta(hours=-6))),
                       date_to="2026-11-02T00:00:00-06:00")
    assert seen["date_from"] == "2026-11-01T12:00:00Z"
    assert seen["date_to"] == "2026-11-02T06:00:00Z"


def test_numbers_limits_and_cleaning():
    c, t, _ = make(no_network)
    with pytest.raises(ic.InvalidRequestError):
        c.alerts.list_alerts(numbers=[str(5550100 + i) for i in range(26)])
    assert _spec.encode_query("listAlerts", {"numbers": ["+1 (555) 555-0142", "2101"]}) == {"numbers": "5555550142,2101"}
    with pytest.raises(ic.InvalidRequestError):
        _spec.encode_query("listAlerts", {"numbers": ["555*0142"]})
    assert t.requests == []


def test_location_ids_capped_at_50_and_checked():
    ids = [f"0193b6c2-6b29-7a51-b0e4-{i:012d}" for i in range(51)]
    with pytest.raises(ic.InvalidRequestError):
        _spec.encode_query("listCalls", {"location_id": ids})
    assert _spec.encode_query("listCalls", {"location_id": ids[:2]}) == {"location_id": ",".join(ids[:2])}
    with pytest.raises(ic.InvalidRequestError):
        _spec.encode_query("listCalls", {"location_id": ["not-a-uuid"]})


def test_enums_and_true_only_flags():
    with pytest.raises(ic.InvalidRequestError):
        _spec.encode_query("listCalls", {"status": "COMPLETED"})
    with pytest.raises(ic.InvalidRequestError):
        _spec.encode_query("listCalls", {"has_open_tasks": False})
    assert _spec.encode_query("listCalls", {"has_open_tasks": True, "multi_leg": False}) == {
        "has_open_tasks": "true", "multi_leg": "false"}
    with pytest.raises(ic.InvalidRequestError):
        _spec.encode_query("listCalls", {"limit": 101})
    with pytest.raises(ic.InvalidRequestError):
        _spec.encode_query("getInsightsDashboard", {"start": "2026-11-01T00:00:00Z"})  # end is required
    assert _spec.encode_query("listTasks", {"due_on": "2026-11-05"}) == {"due_on": "2026-11-05"}


# ------------------------------------------------------------------ paging

def test_iterator_follows_cursors_with_limit_100():
    seen = []

    def h(r):
        if r.url.path.endswith("/auth/login"):
            return login_ok(r)
        q = dict(r.url.params)
        seen.append(q)
        cur = q.get("cursor")
        if cur is None:
            return httpx.Response(200, json={"data": {"summary": {"total_calls": 3}, "calls": [{"id": "1"}]},
                                             "meta": {"has_more": True, "next_cursor": "c+/=1", "limit": 100}})
        if cur == "c+/=1":
            return httpx.Response(200, json={"data": {"calls": [{"id": "2"}]},
                                             "meta": {"has_more": True, "next_cursor": "c2"}})
        return httpx.Response(200, json={"data": {"calls": [{"id": "3"}]}, "meta": {"has_more": False,
                                                                                    "next_cursor": None}})
    c, _, _ = make(h)
    assert [x["id"] for x in c.calls.iter_calls()] == ["1", "2", "3"]
    assert all(q["limit"] == "100" for q in seen)
    first = c.calls.list_calls(limit=1)
    assert first.has_more and first.next_cursor == "c+/=1" and first.total == 3


def test_page_shapes():
    companies = ic.Page.from_body({"data": [{"type": "company", "attributes": {"id": "x"}}], "has_more": True,
                                   "next_cursor": "n", "total_count": 7})
    assert companies.items == [{"id": "x"}] and companies.next_cursor == "n" and companies.total == 7
    rules = ic.Page.from_body({"data": [], "pagination": {"has_more": False, "next_cursor": None}})
    assert rules.items == [] and not rules.has_more


# ------------------------------------------------------------------ user create

def test_idempotency_key_reused_and_identity_encoding_on_retry():
    seen = []

    def h(r):
        if r.url.path.endswith("/auth/login"):
            return login_ok(r)
        seen.append((r.headers.get("Idempotency-Key"), r.headers.get("Accept-Encoding")))
        if len(seen) == 1:
            return httpx.Response(503, json={"error": {"message": "busy"}})
        return httpx.Response(201, json={"data": {"type": "company_user", "attributes": {"id": UID}}})
    c, _, _ = make(h)
    c.users.create_company_user(CID, {"email": "sam@example.com", "first_name": "S", "last_name": "O",
                                      "role": "customer_admin"})
    assert len(seen) == 2 and seen[0][0] == seen[1][0] and seen[0][0]
    assert seen[1][1] == "identity" and seen[0][1] != "identity"


def test_half_create_422_recovers_by_email():
    calls = []

    def h(r):
        p, m = r.url.path, r.method
        if p.endswith("/auth/login"):
            return login_ok(r)
        calls.append((m, p.replace("/api/v1", ""), dict(r.url.params)))
        if m == "POST" and p.endswith("/users"):
            return httpx.Response(422, json={"error": {"code": "VALIDATION_ERROR", "message": "One or more locations not found"}})
        if m == "GET" and p.endswith(f"/companies/{CID}/users"):
            return httpx.Response(200, json={"data": [{"type": "company_user", "attributes": {
                "id": UID, "email": "Sam@Example.com", "status": "invited"}}], "pagination": {"has_more": False}})
        if m == "PATCH":
            assert json.loads(r.content) == {"location_ids": [LID]}
            return httpx.Response(200, json={"data": {"type": "company_user", "attributes": {"id": UID}}})
        if m == "GET":
            return httpx.Response(200, json={"data": {"type": "company_user", "attributes": {
                "id": UID, "locations": [{"location_id": LID}]}}})
        return httpx.Response(500)
    c, _, _ = make(h)
    out = c.users.create_company_user(CID, {"email": "sam@example.com", "first_name": "S", "last_name": "O",
                                            "role": "frontline_user", "location_ids": [LID]})
    assert out["data"]["attributes"]["id"] == UID
    assert [x[0] for x in calls] == ["POST", "GET", "PATCH", "GET"]
    assert calls[1][2]["search"] == "sam@example.com"


def test_422_without_user_reraises():
    def h(r):
        if r.url.path.endswith("/auth/login"):
            return login_ok(r)
        if r.method == "POST":
            return httpx.Response(422, json={"error": {"code": "ROLE_NOT_ASSIGNABLE", "message": "no"}})
        return httpx.Response(200, json={"data": [], "pagination": {"has_more": False}})
    c, _, _ = make(h)
    with pytest.raises(ic.ValidationError):
        c.users.create_company_user(CID, {"email": "x@example.com", "first_name": "S", "last_name": "O",
                                          "role": "customer_admin"})


# ------------------------------------------------------------------ connectors

def connector_server(outcome):
    state = {"polls": 0, "status": "connecting"}

    def h(r):
        p, m = r.url.path, r.method
        if p.endswith("/auth/login"):
            return login_ok(r)
        if m == "POST" and p.endswith("/connectors"):
            return httpx.Response(202, json={"data": {"id": CONN, "status": "connecting"}})
        if m == "POST" and p.endswith("/deactivate"):
            state["status"] = "deactivating"
            return httpx.Response(202, json={"data": {"id": CONN, "status": "deactivating"}})
        if m == "GET":
            state["polls"] += 1
            if state["status"] == "connecting" and state["polls"] >= 3:
                state["status"] = outcome
            elif state["status"] == "deactivating":
                state["status"] = "inactive"
            data = {"id": CONN, "status": state["status"]}
            if state["status"] == "error":
                data.update(state_reason="invalid_permissions", status_message="The key was refused.")
            return httpx.Response(200, json={"data": data})
        return httpx.Response(500)
    return h


BODY = {"name": "Main - NetSapiens", "type": "netsapiens",
        "config": {"api_url": "https://pbx.example.com/ns-api/v2", "domain": "d.example.com", "api_key": "k"}}


def test_connector_create_waits_until_active():
    c, t, sleeps = make(connector_server("active"))
    out = c.connectors.create_connector(LID, BODY)
    assert out["data"]["status"] == "active"
    assert sleeps == [10.0, 10.0]


def test_connector_error_raises_with_state_reason():
    c, _, _ = make(connector_server("error"))
    with pytest.raises(ic.ConnectorError) as e:
        c.connectors.create_connector(LID, BODY)
    assert e.value.state_reason == "invalid_permissions"


def test_connector_deactivate_waits_for_inactive_and_timeout():
    c, _, _ = make(connector_server("active"))
    assert c.connectors.deactivate_connector(LID, CONN)["data"]["status"] == "inactive"
    c2, _, _ = make(connector_server("never"))
    with pytest.raises(ic.ConnectorTimeoutError):
        c2.connectors.create_connector(LID, BODY, timeout=0)

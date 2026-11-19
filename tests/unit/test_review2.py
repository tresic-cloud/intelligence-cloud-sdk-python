"""Company matching, integration users, connector re-runs, offboarding, receivers, tokens and errors."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import httpx
import pytest

import intelligence_cloud as ic
from intelligence_cloud import _spec

from .fake_api import RESELLER, FakeAPI, new_id
from .test_client import UID, login_ok, make, token_body
from .test_workflows import CONN, spec, user

SAMPLE = Path(__file__).resolve().parents[2] / "examples" / "after-call-sample.json"


@pytest.fixture
def api():
    return FakeAPI()


@pytest.fixture
def customer(api):
    return api.client().workflows.provision_seat_customer(spec())


def add_company(api, name, email):
    cid = new_id()
    api.companies[cid] = {"id": cid, "company_name": name, "primary_admin_contact_email": email,
                          "reseller_id": RESELLER, "is_active": True, "mfa_enforced": True,
                          "enabled_products": ["after-call-copilot"]}
    return cid


def writes(api, start=0):
    return [(m, p) for m, p in api.calls[start:] if m != "GET"]


# ------------------------------------------------------------------ company matching (never by name alone)

def test_same_name_other_contact_is_refused_before_any_write(api):
    add_company(api, "Riverbend Auto Group", "someone.else@example.com")
    with pytest.raises(ic.ConflictError) as e:
        api.client().workflows.provision_seat_customer(spec())
    assert e.value.code == "company_name_conflict"
    assert "company_id" in str(e.value)
    assert writes(api) == []


def test_same_name_and_contact_is_reused(api):
    cid = add_company(api, "Riverbend Auto Group", "PAT@example.com ")
    cust = api.client().workflows.provision_seat_customer(spec())
    assert cust.company_id == cid and "company" in cust.existing
    assert api.count("POST", r"/resellers/[^/]+/companies") == 0


def test_only_the_contact_match_is_used_among_same_names(api):
    add_company(api, "Riverbend Auto Group", "other@example.com")
    mine = add_company(api, "Riverbend Auto Group", "pat@example.com")
    cust = api.client().workflows.provision_seat_customer(spec())
    assert cust.company_id == mine


def test_explicit_company_id_wins(api):
    add_company(api, "Riverbend Auto Group", "other@example.com")
    mine = add_company(api, "Riverbend Auto Group (East)", "pat@example.com")
    cust = api.client().workflows.provision_seat_customer(spec(company_id=mine))
    assert cust.company_id == mine
    assert api.count("POST", r"/resellers/[^/]+/companies") == 0


# ------------------------------------------------------------------ integration users

def seat_with_people(api, customer):
    c = api.client()
    a = c.workflows.add_frontline_user(customer, user(1), "2101")
    b = c.workflows.add_frontline_user(customer, user(3), "2103")
    mgr = c.workflows.add_manager(customer, user(2))
    return c, a, b, mgr


def lines_everywhere(api, customer, mgr_id):
    fa_nums = [n for m in api.fa_config[customer.location_id]["connector_mappings"] for n in m["monitored_numbers"]]
    ih_nums = [n for m in api.ih_setup[customer.location_id]["connector_mappings"] for n in m["monitored_numbers"]]
    mgr_nums = [n for m in api.mappings[mgr_id] for n in m["monitored_numbers"]]
    return sorted(fa_nums), sorted(ih_nums), sorted(mgr_nums)


def test_integration_user_is_tagged_and_holds_every_line(api, customer):
    c, a, b, mgr = seat_with_people(api, customer)
    integ = c.workflows.add_integration_user(customer, user(9))
    assert integ.kind == "integration"
    assert api.users[integ.user_id]["department"] == "integration"
    assert sorted(integ.numbers) == ["2101", "2103"]
    assert api.email_prefs[integ.user_id]["masterEnabled"] is False
    assert {m["id"] for m in c.workflows.list_managers(customer)} == {mgr.user_id}
    assert {u["id"] for u in c.workflows.list_frontline_users(customer)} == {a.user_id, b.user_id}
    assert [u["id"] for u in c.workflows.list_integration_users(customer)] == [integ.user_id]
    # a later end user's line reaches the integration user, like a manager
    c.workflows.add_frontline_user(customer, user(4), "2104")
    assert sorted(n for m in api.mappings[integ.user_id] for n in m["monitored_numbers"]) == ["2101", "2103", "2104"]


def test_integration_user_needs_password_sign_in(api, customer):
    u = user(9)
    u.auth_method = "sso"
    with pytest.raises(ic.InvalidRequestError):
        api.client().workflows.add_integration_user(customer, u)


def test_removing_an_integration_user_keeps_every_line(api, customer):
    c, a, b, mgr = seat_with_people(api, customer)
    integ = c.workflows.add_integration_user(customer, user(9))
    before = lines_everywhere(api, customer, mgr.user_id)
    out = c.workflows.remove_user(customer, integ.user_id)
    assert out["kind"] == "integration" and out["released_numbers"] == []
    assert lines_everywhere(api, customer, mgr.user_id) == before == (["2101", "2103"],) * 3
    assert api.users[integ.user_id]["status"] == "deactivated" and api.mappings[integ.user_id] == []


def test_removing_an_untagged_all_lines_user_keeps_every_line(api, customer):
    """A data user set up by hand (After Call only, every line, no tag) is not a seat."""
    c, a, b, mgr = seat_with_people(api, customer)
    raw = c.workflows._ensure_user(customer, user(8))[0]
    c.products.enable_user_product(customer.location_id, raw, "after-call-copilot")
    c.users.set_numbers(customer.company_id, raw, customer.connector_id, ["2101", "2103"])
    assert sorted(c.workflows._lines(customer)) == ["2101", "2103"]  # multi-line users add no lines
    out = c.workflows.remove_user(customer, raw)
    assert out["kind"] == "integration" and out["released_numbers"] == []
    assert lines_everywhere(api, customer, mgr.user_id) == (["2101", "2103"],) * 3


def test_a_line_another_end_user_holds_is_not_released(api, customer):
    c, a, b, mgr = seat_with_people(api, customer)
    shared = c.workflows.add_frontline_user(customer, user(5), "2101")  # same line as user 1
    out = c.workflows.remove_user(customer, shared.user_id)
    assert out["kind"] == "frontline" and out["released_numbers"] == []
    assert lines_everywhere(api, customer, mgr.user_id) == (["2101", "2103"],) * 3
    out = c.workflows.remove_user(customer, a.user_id)  # now the last holder of 2101
    assert out["released_numbers"] == ["2101"]
    assert lines_everywhere(api, customer, mgr.user_id) == (["2103"],) * 3


def test_sync_numbers_gives_integration_users_exactly_the_lines(api, customer):
    c, a, b, mgr = seat_with_people(api, customer)
    integ = c.workflows.add_integration_user(customer, user(9))
    c.users.set_numbers(customer.company_id, integ.user_id, customer.connector_id, ["2101", "2199"])
    diff = c.workflows.sync_numbers(customer)
    assert diff["managers"][integ.user_id] == {"add": ["2103"], "remove": ["2199"]}
    assert sorted(n for m in api.mappings[integ.user_id] for n in m["monitored_numbers"]) == ["2101", "2103"]


def test_excluded_users_are_invisible(api, customer):
    c, a, b, mgr = seat_with_people(api, customer)
    customer.exclude_user_ids = [a.user_id]
    customer.exclude_emails = ["USER2@example.com"]
    assert {u["id"] for u in c.workflows.list_frontline_users(customer)} == {b.user_id}
    assert c.workflows.list_managers(customer) == []
    assert c.workflows._lines(customer) == ["2103"]


def test_manager_needs_all_three_products(api, customer):
    c, a, b, mgr = seat_with_people(api, customer)
    api.users[mgr.user_id]["_products"].discard("after-call-copilot")
    assert c.workflows.list_managers(customer) == []


# ------------------------------------------------------------------ connector re-runs

def test_rerun_applies_a_fixed_key_to_a_connector_in_error(api):
    api.connector_outcome = "error"
    c = api.client()
    first = c.workflows.provision_seat_customer(spec())
    assert first.connector_status == "error"
    api.connector_outcome = "active"
    fixed = ic.ConnectorSpec(api_url=CONN.api_url, domain=CONN.domain, api_key="NEW-KEY")
    again = c.workflows.provision_seat_customer(spec(connector=fixed, company_id=first.company_id))
    conn = api.connectors[first.connector_id]
    assert again.connector_id == first.connector_id and again.connector_status == "active"
    assert conn["_key"] == "NEW-KEY" and "connector:updated" in again.existing
    assert api.count("PATCH", r"/locations/[^/]+/connectors/[^/]+") == 1
    assert api.count("POST", r"/locations/[^/]+/connectors/[^/]+/reactivate") == 1
    assert api.count("POST", r"/locations/[^/]+/connectors") == 1  # never a second connector


def test_same_domain_under_another_name_is_reused(api, customer):
    renamed = ic.ConnectorSpec(api_url=CONN.api_url, domain=CONN.domain.upper(), api_key="KEY", name="Phones")
    again = api.client().workflows.provision_seat_customer(spec(connector=renamed, company_id=customer.company_id))
    assert again.connector_id == customer.connector_id
    assert api.count("POST", r"/locations/[^/]+/connectors") == 1
    assert api.connectors[customer.connector_id]["name"] == "Phones"


def test_unchanged_active_connector_is_left_alone(api, customer):
    start = len(api.calls)
    api.client().workflows.provision_seat_customer(spec(company_id=customer.company_id))
    assert not [p for m, p in writes(api, start) if "/connectors" in p]


# ------------------------------------------------------------------ offboarding

def test_offboard_customer_order(api, customer):
    c, a, b, mgr = seat_with_people(api, customer)
    integ = c.workflows.add_integration_user(customer, user(9))
    c.intelligence.set_after_call_webhook(customer.location_id, "https://hooks.example.com/ic/" + "x" * 32)
    c.intelligence.set_first_alert_webhook(customer.location_id, "https://hooks.example.com/fa/" + "y" * 32)
    start = len(api.calls)
    out = c.workflows.offboard_customer(customer)
    seq = [p.split("/api/v1")[-1] for m, p in writes(api, start)]
    kinds = [("automation" in p and "hook") or ("first-alert/config" in p and "fa") or
             ("deactivate" in p and "/connectors/" in p and "conn") or
             ("/users/" in p and "user") or ("/deactivate" in p and "company") for p in seq]
    assert kinds == ["hook", "fa", "conn", "user", "company"]
    assert api.after_call_hooks[customer.location_id]["enabled"] is False
    assert api.after_call_hooks[customer.location_id]["webhook_url"].startswith("https://hooks.example.com/")
    assert api.fa_config[customer.location_id]["webhook_url"] is None
    assert api.fa_config[customer.location_id]["connector_mappings"]  # numbers kept
    assert api.connectors[customer.connector_id]["status"] == "inactive"
    assert out["integration_users_deactivated"] == [integ.user_id]
    assert api.users[mgr.user_id]["status"] != "deactivated"
    assert api.companies[customer.company_id]["is_active"] is False
    again = c.workflows.offboard_customer(customer)  # safe to run again
    assert again["company_deactivated"] is False and again["connector_deactivated"] is False


# ------------------------------------------------------------------ receiver

def test_sample_event_parses():
    ev = ic.parse_after_call_event(SAMPLE.read_bytes())
    assert isinstance(ev, ic.AfterCallEvent) and ev.is_test and ev.summary.sentiment == "positive"


def test_other_event_types_are_unknown_not_errors():
    for body in ({"type": "something_new", "version": "2.0", "x": 1}, {"no_type": True}):
        ev = ic.parse_after_call_event(json.dumps(body))
        assert isinstance(ev, ic.UnknownEvent)
    assert ic.parse_after_call_event(b'{"type": "something_new", "version": "2.0"}').type == "something_new"
    with pytest.raises(ic.WebhookPayloadError):
        ic.parse_after_call_event(b"[1, 2]")
    with pytest.raises(ic.WebhookPayloadError):
        ic.parse_after_call_event(b"not json")


def test_body_size_is_capped():
    big = b'{"type": "end_of_call_summary", "pad": "' + b"x" * ic.MAX_EVENT_BYTES + b'"}'
    with pytest.raises(ic.PayloadTooLargeError):
        ic.parse_after_call_event(big)
    with pytest.raises(ic.PayloadTooLargeError):
        ic.parse_after_call_event(SAMPLE.read_bytes(), max_bytes=100)
    assert isinstance(ic.PayloadTooLargeError("x"), ic.WebhookPayloadError)


# ------------------------------------------------------------------ client

def test_base_url_must_be_https():
    with pytest.raises(ic.InvalidRequestError):
        ic.Client(base_url="http://api.example.com/api/v1")
    for ok in ("https://api.example.com/api/v1", "http://localhost:8080/api/v1", "http://127.0.0.1/api/v1"):
        ic.Client(base_url=ok).close()


def test_exception_text_never_carries_server_message():
    secret = "number 5555550142 refused at Other Company - Main"

    def h(r):
        if r.url.path.endswith("/auth/login"):
            return login_ok(r)
        return httpx.Response(422, json={"error": {"code": "VALIDATION_ERROR", "message": secret,
                                                   "request_id": "req-1"}})
    c, _, _ = make(h)
    with pytest.raises(ic.ValidationError) as e:
        c.account.get_me()
    assert e.value.message == secret
    assert str(e.value) == "HTTP 422 VALIDATION_ERROR (request_id req-1)"


def test_retry_after_above_60_is_not_waited_out():
    def h(r):
        if r.url.path.endswith("/auth/login"):
            return login_ok(r)
        return httpx.Response(429, headers={"Retry-After": "3600"}, json={"error": {"code": "RATE_LIMITED"}})
    c, t, sleeps = make(h)
    with pytest.raises(ic.RateLimitError) as e:
        c.account.get_me()
    assert sleeps == [] and e.value.retry_after == 3600
    assert len([r for r in t.requests if r.url.path.endswith("/me")]) == 1


def test_login_rate_limit_wait_is_configurable():
    def h(r):
        return httpx.Response(429, json={"error": {"code": "RATE_LIMITED"}})
    c, t, sleeps = make(h, login_rate_limit_wait=0)
    with pytest.raises(ic.RateLimitError):
        c.login()
    assert sleeps == [] and len(t.requests) == 1


def test_refresh_429_retries_the_same_refresh_token_without_signing_in():
    sent = []
    state = {"refresh_429": 2}

    def h(r):
        p = r.url.path
        if p.endswith("/auth/login"):
            sent.append(("login", None))
            return httpx.Response(200, json=token_body(1))
        if p.endswith("/auth/refresh"):
            sent.append(("refresh", json.loads(r.content)["refresh_token"]))
            if state["refresh_429"]:
                state["refresh_429"] -= 1
                return httpx.Response(429, headers={"Retry-After": "2"}, json={})
            return httpx.Response(200, json=token_body(2))
        if r.headers["Authorization"] == "Bearer A1":
            return httpx.Response(401, json={"error": {"code": "UNAUTHORIZED"}})
        return httpx.Response(200, json={"data": {"id": UID, "role": "frontline_user"}})
    c, t, sleeps = make(h)
    c.account.get_me()
    assert sent == [("login", None), ("refresh", "R1"), ("refresh", "R1"), ("refresh", "R1")]
    assert sleeps == [2.0, 2.0]


def test_naive_datetime_refused():
    from datetime import datetime
    with pytest.raises(ic.InvalidRequestError):
        _spec.format_datetime(datetime(2026, 11, 1), "date_from")


def test_nanp_numbers_sent_as_ten_digits():
    q = _spec.encode_query("listAlerts", {"numbers": ["+1 555-555-0142", "15555550143", "5555550144", "2101"]})
    assert q == {"numbers": "5555550142,5555550143,5555550144,2101"}


def test_keep_unknown_fields_only_on_lifecycle_reads():
    def h(r):
        p = r.url.path
        if p.endswith("/auth/login"):
            return login_ok(r)
        if p.endswith("/me"):
            return httpx.Response(200, json={"data": {"id": UID, "role": "frontline_user", "unexpected_flag": True}})
        if "/calls/" in p:
            return httpx.Response(200, json={"data": {"id": UID, "new_field": 1, "analysis": {"unexpected_field": 1},
                                                      "vcon": {"recording_url": "u", "unexpected_id": "x"}}})
        if "/connectors/" in p:
            return httpx.Response(200, json={"data": {"id": UID, "status": "active", "new_field": 2,
                                                      "config": {"domain": "d", "unexpected_ref": "secret"},
                                                      "invitation_link": "https://app.example.com/x"}})
        return httpx.Response(404, json={})
    c, _, _ = make(h, keep_unknown_fields=True)
    conn = c.connectors.get_connector("l", UID)["data"]
    assert conn["new_field"] == 2 and conn["config"] == {"domain": "d"} and "invitation_link" not in conn
    call = c.calls.get_call(UID)["data"]
    assert "new_field" not in call and "unexpected_field" not in json.dumps(call)
    assert call.get("vcon", {}).keys() <= {"recording_url", "recording_url_expires_at"}
    assert c.account.get_me()["data"] == {"id": UID, "role": "frontline_user"}
    c2, _, _ = make(h)
    assert "new_field" not in c2.connectors.get_connector("l", UID)["data"]


def test_file_token_store_round_trip_and_lock(tmp_path):
    path = tmp_path / "tokens.json"
    store = ic.FileTokenStore(str(path))
    assert store.get() is None
    store.set(ic.Tokens(access_token="A", refresh_token="R", expires_at=123.0))
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    assert store.get().refresh_token == "R"
    order = []

    def other():
        with store.lock():
            order.append("other")
    with store.lock():
        th = threading.Thread(target=other)
        th.start()
        th.join(0.2)
        order.append("first")
    th.join()
    assert order == ["first", "other"]
    store.set(None)
    assert store.get() is None


def test_client_renews_inside_the_store_lock():
    events = []

    class LockingStore(ic.MemoryTokenStore):
        def lock(self):
            class _L:
                def __enter__(self_inner):
                    events.append("lock")

                def __exit__(self_inner, *a):
                    events.append("unlock")
            return _L()

    def h(r):
        if r.url.path.endswith("/auth/login"):
            events.append("login")
            return login_ok(r)
        return httpx.Response(200, json={"data": {"id": UID, "role": "frontline_user"}})
    c, _, _ = make(h, token_store=LockingStore())
    c.account.get_me()
    assert events == ["lock", "login", "unlock"]


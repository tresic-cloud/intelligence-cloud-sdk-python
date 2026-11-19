"""Live suite against the real API. Opt-in: IC_LIVE=1. Point it at a test reseller, never at a customer.

Everything comes from the environment; nothing about the test tenant is written here.
  IC_RESELLER_USER / IC_RESELLER_PASSWORD     reseller admin integration user
  IC_FRONTLINE_USER / IC_FRONTLINE_PASSWORD   frontline integration user, READ ONLY (shapes and counts only)
  SBX_NS_API_URL / SBX_NS_DOMAIN / SBX_NA_API_KEY   phone-system connector settings for the test company
  IC_LIVE_COMPANY_NAME        the test company this suite creates (or finds) and deactivates at the end
  IC_LIVE_COMPANY_CODE        its company code (optional)
  IC_LIVE_LOCATION_NAME       its location (default "SDK Test - Main")
  IC_LIVE_COMPANY_SEARCH      a company-name prefix with at least one match, for the paging check
                              (default: IC_LIVE_COMPANY_NAME)
  IC_LIVE_EMAIL_PREFIX / IC_LIVE_EMAIL_DOMAIN   test users are <prefix>-<n>@<domain>
                              (n = 0 is the company's primary contact, who is always emailed an invitation)
  IC_LIVE_SSO_DOMAIN          a domain to claim and release (optional; the SSO step is skipped without it)
  IC_LIVE_THREAT_PHRASES_FILE Customer Threat phrases, one per line
  IC_LIVE_EXPECT_CONNECTOR    the connector status the test key reaches: "active" or "error" (default "error")
  IC_LIVE_FREE_EXTENSION      an extension no other location monitors
  IC_LIVE_CONFLICT_EXTENSION  an extension another location monitors (optional; the 409 check is skipped)
  IC_LIVE_VERTICAL            vertical key for the location (default "csps-msps")

Safety:
- Each credential signs in once per run. Logout is never called.
- Writes go only to IC_LIVE_COMPANY_NAME and are deactivated at the end.
- Users are created with send_invitation=False.
- Nothing from conversation data is printed or stored; assertions compare key names and counts only.
- Optional: IC_LIVE_REPORT=<path> writes the key names the server sent beyond the published schema.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import intelligence_cloud as ic
from intelligence_cloud import _spec
from intelligence_cloud._base import unwrap

pytestmark = pytest.mark.skipif(os.environ.get("IC_LIVE") != "1", reason="live suite: set IC_LIVE=1")

LIVE = os.environ.get("IC_LIVE") == "1"
COMPANY = os.environ.get("IC_LIVE_COMPANY_NAME", "")
LOCATION = os.environ.get("IC_LIVE_LOCATION_NAME", "SDK Test - Main")
SSO_DOMAIN = os.environ.get("IC_LIVE_SSO_DOMAIN", "")
EXPECT_CONNECTOR = os.environ.get("IC_LIVE_EXPECT_CONNECTOR", "error")
FREE_EXT = os.environ.get("IC_LIVE_FREE_EXTENSION", "")
CONFLICT_EXT = os.environ.get("IC_LIVE_CONFLICT_EXTENSION", "")
if LIVE and not (COMPANY and FREE_EXT and os.environ.get("IC_LIVE_EMAIL_PREFIX") and os.environ.get("IC_LIVE_EMAIL_DOMAIN")):
    pytest.exit("Set IC_LIVE_COMPANY_NAME, IC_LIVE_FREE_EXTENSION, IC_LIVE_EMAIL_PREFIX and IC_LIVE_EMAIL_DOMAIN", 2)


def email(n: int) -> str:
    return f"{os.environ['IC_LIVE_EMAIL_PREFIX']}-{n}@{os.environ['IC_LIVE_EMAIL_DOMAIN']}"

STATE: dict = {}
REPORT: dict = {}
NOW = datetime.now(timezone.utc)


def env(name):
    v = os.environ.get(name)
    if not v:
        pytest.skip(f"{name} not set")
    return v


@pytest.fixture(scope="module")
def admin():
    c = ic.Client(email=env("IC_RESELLER_USER"), password=env("IC_RESELLER_PASSWORD"), user_agent="sdk-live-tests")
    c.login()
    yield c
    c.close()  # never logout: it would end every session of this user


@pytest.fixture(scope="module")
def frontline():
    c = ic.Client(email=env("IC_FRONTLINE_USER"), password=env("IC_FRONTLINE_PASSWORD"), user_agent="sdk-live-tests")
    c.login()
    yield c
    c.close()
    if os.environ.get("IC_LIVE_REPORT"):
        REPORT["_outcomes"] = {k: STATE.get(k) for k in ("conflict_status", "recording", "ac_test", "fa_test")}
        with open(os.environ["IC_LIVE_REPORT"], "w") as fh:
            json.dump(REPORT, fh, indent=1, sort_keys=True)


def raw_keys(client, op_id, path, query=None):
    """Key names the server sent that the published schema does not list (names only, no values)."""
    op, url_path, params = client._build(op_id, path, query or {}, None)
    resp = client._send_with_retries(op["method"], url_path, op_id=op_id, params=params)
    body = client._json(resp)
    projected = _spec.project_response(op_id, resp.status_code, body)
    extra = sorted(_key_paths(body) - _key_paths(projected))
    REPORT[op_id] = {"status": resp.status_code, "dropped_keys": extra}
    return extra


def _key_paths(x, prefix=""):
    out = set()
    if isinstance(x, dict):
        for k, v in x.items():
            p = f"{prefix}.{k}" if prefix else k
            out.add(p)
            out |= _key_paths(v, p)
    elif isinstance(x, list):
        for v in x[:20]:
            out |= _key_paths(v, prefix + "[]")
    return out


# ====================================================================== admin: reads and checks

def test_admin_identity(admin):
    me = admin.intelligence.whoami()
    assert me["role"] == "reseller_admin" and me.get("reseller_id")
    STATE["reseller_id"] = me["reseller_id"]
    with pytest.raises(ic.FrontlineRequiredError):
        admin.intelligence.search_calls()


def test_admin_catalogue_reads(admin):
    keys = {p["key"] for p in unwrap(admin.products.list_products())}
    assert {"after-call-copilot", "first-alert-copilot", "insights-hub"} <= keys
    verticals = unwrap(admin.locations.list_verticals())
    vid = next(v["id"] for v in verticals if v.get("key") == os.environ.get("IC_LIVE_VERTICAL", "csps-msps"))
    STATE["vertical"] = vid
    types = {t["key"] for t in unwrap(admin.connectors.list_connector_types())}
    assert "netsapiens" in types


def test_admin_list_and_page(admin):
    rid = STATE["reseller_id"]
    search = os.environ.get("IC_LIVE_COMPANY_SEARCH") or COMPANY
    page = admin.companies.list_companies(rid, search=search, limit=1)
    if not page.total:
        pytest.skip("no company matches IC_LIVE_COMPANY_SEARCH yet")
    assert len(page.items) == 1
    names = [c["company_name"] for c in admin.companies.iter_companies(rid, search=search)]
    assert len(names) == page.total


def test_admin_errors(admin):
    with pytest.raises(ic.NotFoundError):
        admin.companies.get_company(str(uuid.uuid4()))
    with pytest.raises(ic.InvalidRequestError):
        admin.users.list_company_users(str(uuid.uuid4()), status="everyone")
    with pytest.raises(TypeError):
        admin.users.list_company_users(str(uuid.uuid4()), product="insights-hub")  # type: ignore[call-arg]


# ====================================================================== admin: Seat lifecycle

def _threat_phrases(admin):
    if "phrases" not in STATE:
        with open(env("IC_LIVE_THREAT_PHRASES_FILE")) as fh:
            STATE["phrases"] = [line.strip() for line in fh if line.strip()]
    return STATE["phrases"]


def _spec_for(admin):
    return ic.SeatCustomerSpec(
        company_name=COMPANY, admin_name="SDK Test Admin", admin_email=email(0),
        admin_phone="+15555550100", company_code=os.environ.get("IC_LIVE_COMPANY_CODE") or None,
        mfa_off=True, reactivate=True,
        threat_phrases=_threat_phrases(admin),
        location=ic.LocationSpec(name=LOCATION, street="1 Example Way", city="Springfield", state="IL",
                                 country="US", zipcode="62701", vertical=STATE["vertical"]),
        connector=ic.ConnectorSpec(api_url=env("SBX_NS_API_URL"), domain=env("SBX_NS_DOMAIN"),
                                   api_key=env("SBX_NA_API_KEY"), name=f"{LOCATION} - NetSapiens", timeout=90),
        sso_domain=SSO_DOMAIN or None,
    )


@pytest.fixture(scope="module")
def customer(admin):
    cust = admin.workflows.provision_seat_customer(_spec_for(admin))
    STATE["customer"] = cust
    yield cust
    _cleanup(admin, cust)


def _cleanup(admin, cust):
    """Deactivate everything this run created or reactivated."""
    errors = []

    def attempt(fn, *a, **kw):
        try:
            fn(*a, **kw)
        except ic.ConflictError:
            pass  # already inactive
        except Exception as exc:  # keep cleaning up
            errors.append(f"{fn.__name__}: {type(exc).__name__}")
    for uid in STATE.get("users", []):
        attempt(admin.users.deactivate_company_user, cust.company_id, uid)
    if cust.connector_id:
        attempt(admin.connectors.deactivate_connector, cust.location_id, cust.connector_id, timeout=60)
    if cust.sso_domain_id:
        attempt(admin.sso.remove_company_domain, cust.company_id, cust.sso_domain_id)
    attempt(admin.intelligence.set_first_alert_webhook, cust.location_id, None)
    attempt(admin.locations.deactivate_location, cust.company_id, cust.location_id)
    attempt(admin.companies.deactivate_company, cust.company_id)
    assert not errors, errors


def test_provision_seat_customer(admin, customer):
    assert customer.company_id and customer.location_id
    assert customer.manager_alerts_group_id and customer.insights_hub_group_id
    assert customer.upset_customer_rule_id and customer.customer_threat_rule_id
    company = unwrap(admin.companies.get_company(customer.company_id))
    assert company["mfa_enforced"] is False and company["is_active"]
    assert customer.connector_status == EXPECT_CONNECTOR
    if EXPECT_CONNECTOR == "error":
        assert customer.connector_state_reason == "invalid_permissions"
    if SSO_DOMAIN:
        assert customer.sso_txt_record and customer.sso_txt_record["name"] == "_ic-verify." + SSO_DOMAIN
    threat = unwrap(admin.first_alert.get_alert_rule(customer.location_id, customer.customer_threat_rule_id))
    kw = next(t for t in threat["triggers"] if t["trigger_type"] == "keyword_match")["config"]
    assert sorted(kw["keywords"]) == sorted(_threat_phrases(admin))
    assert [g["id"] for g in threat["groups"]] == [customer.manager_alerts_group_id]
    setup = unwrap(admin.insights_hub.get_insights_hub_setup(customer.location_id))
    assert customer.insights_hub_group_id in setup["group_access"]
    assert unwrap(admin.insights_hub.get_insights_hub_config(customer.location_id))["monitor_all_numbers"] is True
    raw_keys(admin, "getConnector", {"locationId": customer.location_id, "connectorId": customer.connector_id})
    raw_keys(admin, "getCompany", {"companyId": customer.company_id})


def test_provision_is_idempotent(admin, customer):
    again = admin.workflows.provision_seat_customer(_spec_for(admin))
    assert not [x for x in again.created if x != "connector"]
    assert again.location_id == customer.location_id
    assert again.customer_threat_rule_id == customer.customer_threat_rule_id
    got = admin.workflows.get_seat_customer(customer.company_id)
    assert got.manager_alerts_group_id == customer.manager_alerts_group_id
    assert got.connector_id == customer.connector_id


def test_connector_polling_to_error(admin, customer):
    if EXPECT_CONNECTOR != "error":
        pytest.skip("the test key connects")
    out = unwrap(admin.connectors.deactivate_connector(customer.location_id, customer.connector_id, timeout=60))
    assert out["status"] == "inactive"
    with pytest.raises(ic.ConnectorError) as e:
        admin.connectors.reactivate_connector(customer.location_id, customer.connector_id, timeout=90)
    assert e.value.state_reason == "invalid_permissions"
    ok = unwrap(admin.connectors.test_connector(customer.location_id, {"type": "netsapiens", "config": {
        "api_url": env("SBX_NS_API_URL"), "domain": env("SBX_NS_DOMAIN"), "api_key": env("SBX_NA_API_KEY")}}))
    assert set(ok) == {"success"}


def test_add_manager(admin, customer):
    mgr = admin.workflows.add_manager(customer, ic.UserSpec(email(2), "SDK", "Manager",
                                                            send_invitation=False))
    assert not mgr.invited
    for rid in (customer.upset_customer_rule_id, customer.customer_threat_rule_id):
        assert unwrap(admin.first_alert.get_alert_rule(customer.location_id, rid))["enabled"]  # switched on
    STATE.setdefault("users", []).append(mgr.user_id)
    STATE["manager"] = mgr.user_id
    row = unwrap(admin.users.get_location_user(customer.location_id, mgr.user_id))
    assert set(row["enabled_products"]) == {"after-call-copilot", "first-alert-copilot", "insights-hub"}
    access = unwrap(admin.insights_hub.get_user_insights_hub_access(customer.location_id, mgr.user_id))
    assert access["enabled"] is True
    prefs = admin.first_alert.get_alert_notification_preferences(customer.location_id, mgr.user_id)
    assert prefs["emailNotifications"]["masterEnabled"] is True
    assert {a["alertId"] for a in prefs["emailNotifications"]["alerts"]} == {
        customer.upset_customer_rule_id, customer.customer_threat_rule_id}
    raw_keys(admin, "getAlertNotificationPreferences", {"locationId": customer.location_id, "userId": mgr.user_id})


def test_add_frontline_user_mapping_422(admin, customer):
    # the connector is not active: the user is created (not invited), the mapping is refused
    if EXPECT_CONNECTOR != "error":
        pytest.skip("the test key connects")
    with pytest.raises(ic.ExtensionMappingError) as e:
        admin.workflows.add_frontline_user(customer, ic.UserSpec(email(1), "SDK", "Agent",
                                                                 send_invitation=False), FREE_EXT)
    assert e.value.cause.status == 422
    uid = e.value.user_id
    STATE.setdefault("users", []).append(uid)
    STATE["frontline"] = uid
    row = unwrap(admin.users.get_location_user(customer.location_id, uid))
    assert row["enabled_products"] == ["after-call-copilot"]
    raw_keys(admin, "getCompanyUser", {"companyId": customer.company_id, "userId": uid})


def test_add_frontline_user_mapping_success(admin, customer):
    """With an active connector: the end user's line maps, and reaches managers, First Alert and Insights Hub."""
    if EXPECT_CONNECTOR != "active":
        pytest.skip("needs a read/write phone-system key (IC_LIVE_EXPECT_CONNECTOR=active)")
    user = admin.workflows.add_frontline_user(customer, ic.UserSpec(email(1), "SDK", "Agent",
                                                                    send_invitation=False), FREE_EXT)
    STATE.setdefault("users", []).append(user.user_id)
    STATE["frontline"] = user.user_id
    assert admin.users.user_numbers(customer.company_id, user.user_id, customer.connector_id) == [FREE_EXT]
    assert FREE_EXT in admin.users.user_numbers(customer.company_id, STATE["manager"], customer.connector_id)
    assert FREE_EXT in admin.workflows._fa_numbers(customer) and FREE_EXT in admin.workflows._ih_numbers(customer)


def test_classification(admin, customer):
    assert [u["id"] for u in admin.workflows.list_frontline_users(customer)] == [STATE["frontline"]]
    assert [u["id"] for u in admin.workflows.list_managers(customer)] == [STATE["manager"]]


def test_change_user_extension_422(admin, customer):
    if EXPECT_CONNECTOR != "error":
        pytest.skip("the test key connects")
    with pytest.raises(ic.ExtensionMappingError) as e:
        admin.workflows.change_user_extension(customer, STATE["frontline"], FREE_EXT, FREE_EXT + "0")
    assert e.value.cause.status == 422


def test_extension_conflict_409_is_sanitised(admin, customer):
    if not CONFLICT_EXT:
        pytest.skip("IC_LIVE_CONFLICT_EXTENSION not set")
    with pytest.raises((ic.ConflictError, ic.ValidationError)) as e:
        admin.after_call_settings.update_user_after_call_settings(
            customer.location_id, STATE["manager"],
            {"connector_mappings": [{"connector_id": customer.connector_id, "monitored_numbers": [CONFLICT_EXT]}]})
    STATE["conflict_status"] = e.value.status
    if isinstance(e.value, ic.ConflictError):
        assert e.value.message == "Extension is already monitored at another location."
        assert e.value.extensions == [CONFLICT_EXT]


def test_sync_numbers(admin, customer):
    diff = admin.workflows.sync_numbers(customer, dry_run=True)
    assert not diff["applied"]
    assert admin.workflows.sync_numbers(customer)["applied"]


def test_webhook_configuration(admin, customer):
    lid = customer.location_id
    token = uuid.uuid4().hex
    out = admin.intelligence.set_after_call_webhook(lid, f"https://example.com/ic-sdk/{token}", enabled=False)
    assert out["enabled"] is False
    got = admin.intelligence.get_after_call_webhook(lid)
    assert got["webhook_url"].endswith(token)
    res = admin.intelligence.test_after_call_webhook(lid)
    assert isinstance(res.success, bool)
    STATE["ac_test"] = (res.success, res.http_status)
    fa_url = f"https://example.com/ic-sdk-fa/{token}"
    admin.intelligence.set_first_alert_webhook(lid, fa_url)
    assert admin.intelligence.get_first_alert_webhook(lid) == fa_url
    res = admin.intelligence.test_first_alert_webhook(lid)
    STATE["fa_test"] = (res.success, res.http_status)
    admin.intelligence.set_first_alert_webhook(lid, None)
    assert admin.intelligence.get_first_alert_webhook(lid) is None
    raw_keys(admin, "getAfterCallWebhook", {"locationId": lid})


def test_remove_users(admin, customer):
    again = admin.workflows.provision_seat_customer(
        ic.SeatCustomerSpec(**{**vars(_spec_for(admin)), "threat_phrases": None, "connector": None, "sso_domain": None}))
    assert again.customer_threat_rule_id == customer.customer_threat_rule_id  # re-run without phrases keeps the rule
    out = admin.workflows.remove_user(customer, STATE["frontline"])
    assert out["kind"] == "frontline"
    out = admin.workflows.remove_user(customer, STATE["manager"])
    assert out["kind"] == "manager"
    for uid in (STATE["frontline"], STATE["manager"]):
        assert unwrap(admin.users.get_company_user(customer.company_id, uid))["status"] == "deactivated"
        assert not admin.groups.user_group_ids(customer.location_id, uid)
    assert admin.workflows.list_managers(customer) == []


# ====================================================================== frontline: read only

def test_frontline_identity(frontline):
    me = frontline.intelligence.require_frontline()
    assert me["role"] == "frontline_user"
    raw_keys(frontline, "getMe", {})


def test_frontline_calls(frontline):
    since = NOW - timedelta(days=2)
    page = frontline.intelligence.search_calls(date_from=since, limit=5)
    assert len(page.items) <= 5 and isinstance(page.total, int)
    allowed = set(_spec.schema_by_name("CallListItem")["properties"])
    assert all(set(c) <= allowed for c in page.items)
    ids = []
    for i, call in enumerate(frontline.intelligence.iter_calls(date_from=since)):
        ids.append(call["id"])
        if i >= 149:
            break
    assert len(ids) == len(set(ids))
    if ids:
        STATE["call_id"] = ids[0]
        detail = frontline.intelligence.get_call(ids[0])
        assert detail["id"] == ids[0]
        link = frontline.intelligence.get_recording_url(ids[0])
        if link is not None:
            assert link.url.startswith("https://") and set(vars(link)) == {"url", "expires_at"}
            left = (link.expires_at - datetime.now(timezone.utc)).total_seconds()
            assert 0 < left <= 121 * 60
            STATE["recording"] = True
        assert "vcon" not in detail or set(detail["vcon"]) <= {"recording_url", "recording_url_expires_at"}
        transcript = frontline.intelligence.get_transcript(ids[0])
        assert isinstance(transcript, list)
        assert all(set(seg) <= {"time", "speaker", "name", "text"} for seg in transcript)
        raw_keys(frontline, "getCall", {"callId": ids[0]})
        raw_keys(frontline, "getCallTranscript", {"callId": ids[0]})
    raw_keys(frontline, "listCalls", {}, {"date_from": since, "limit": 5})


def test_frontline_alerts(frontline):
    since = NOW - timedelta(days=30)
    page = frontline.intelligence.search_alerts(date_from=since, limit=3)
    assert len(page.items) <= 3
    if page.items:
        first = page.items[0]
        again = frontline.intelligence.get_alert(first["id"])
        assert again is not None and again["id"] == first["id"]
        if first.get("keywords"):
            named = frontline.intelligence.search_alerts(alert_name=first["keywords"][0], date_from=since, limit=1)
            assert named.total and named.total >= 1
    dash = frontline.intelligence.get_alerts_dashboard(date_from=since)
    assert set(dash) <= {"kpis", "top_triggered", "recent_alerts"}
    raw_keys(frontline, "listAlerts", {}, {"date_from": since, "limit": 3})


def test_frontline_tasks_and_insights(frontline):
    tasks = frontline.intelligence.list_tasks(status="open", limit=3)
    assert len(tasks.items) <= 3
    dash = frontline.intelligence.get_insights_dashboard(start=NOW - timedelta(days=7), end=NOW, trending_limit=3)
    assert set(dash) <= {"stats", "trending_topics", "topic_call_volumes"}
    vols = dash.get("topic_call_volumes") or []
    if vols:
        topic = frontline.intelligence.list_topic_calls(vols[0]["slug"], limit=2)
        assert len(topic.items) <= 2
    raw_keys(frontline, "listTasks", {}, {"limit": 3})


def test_frontline_filter_guards(frontline):
    with pytest.raises(ic.InvalidRequestError):
        frontline.intelligence.search_calls(date_from="2026-11-01")
    with pytest.raises(ic.InvalidRequestError):
        frontline.intelligence.search_calls(text="a")
    with pytest.raises(ic.InvalidRequestError):
        frontline.intelligence.search_alerts(numbers=[str(5550100 + i) for i in range(26)])


def test_frontline_token_refresh(frontline):
    store = frontline._store
    tokens = store.get()
    store.set(ic.Tokens("not-a-valid-token", tokens.refresh_token, tokens.expires_at))
    frontline.intelligence.whoami()  # 401 -> refresh (rotates) -> retry
    after = store.get()
    assert after.refresh_token != tokens.refresh_token
    assert after.access_token != "not-a-valid-token"

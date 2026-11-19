"""Seat lifecycle workflows against the in-memory fake API."""
from __future__ import annotations

import pytest

import intelligence_cloud as ic
from intelligence_cloud.workflows import CUSTOMER_THREAT_RULE, UPSET_CUSTOMER_RULE

from .fake_api import FakeAPI

LOC = ic.LocationSpec(name="Riverbend - Main", street="1 River Rd", city="Springfield", state="IL",
                      country="US", zipcode="62701", vertical="service-providers")
PHRASES = ["example phrase one", "example phrase two"]
CONN = ic.ConnectorSpec(api_url="https://pbx.example.com/ns-api/v2", domain="riverbend.example.com", api_key="KEY")


def spec(**kw):
    base = dict(company_name="Riverbend Auto Group", admin_name="Pat Lee", admin_email="pat@example.com",
                admin_phone="+15555550100", location=LOC, mfa_off=True, connector=CONN, threat_phrases=PHRASES,
                sso_domain="riverbend.example.com")
    base.update(kw)
    return ic.SeatCustomerSpec(**base)


def user(n, invite=False):
    return ic.UserSpec(email=f"user{n}@example.com", first_name="U", last_name=str(n), send_invitation=invite)


def write_paths(api, start):
    return [(m, p.split("/api/v1")[-1]) for m, p in api.calls[start:] if m != "GET"]


@pytest.fixture
def api():
    return FakeAPI()


@pytest.fixture
def customer(api):
    return api.client().workflows.provision_seat_customer(spec())


def test_provision_call_sequence(api):
    c = api.client()
    cust = c.workflows.provision_seat_customer(spec())
    seq = [(m, p.split("/api/v1")[-1]) for m, p in api.calls]
    order = [
        ("POST", r"/resellers/[^/]+/companies"), ("PATCH", r"/companies/[^/]+"),
        ("POST", r"/companies/[^/]+/locations"), ("POST", r"/locations/[^/]+/user-groups"),
        ("POST", r"/locations/[^/]+/first-alert/rules"), ("POST", r"/locations/[^/]+/connectors"),
        ("POST", r"/locations/[^/]+/insights-hub/setup"), ("PATCH", r"/locations/[^/]+/insights-hub/config"),
        ("POST", r"/companies/[^/]+/domains"),
    ]
    import re
    pos = -1
    for m, pat in order:
        idx = next(i for i, (mm, pp) in enumerate(seq) if mm == m and re.match("^" + pat + "$", pp) and i > pos)
        pos = idx
    company = api.companies[cust.company_id]
    assert company["mfa_enforced"] is False
    assert company["enabled_products"] == ["after-call-copilot", "first-alert-copilot", "insights-hub"]
    assert api.count("POST", r"/locations/[^/]+/user-groups") == 2
    assert api.count("POST", r"/locations/[^/]+/first-alert/rules") == 2
    rules = {r["name"]: r for r in api.rules.values()}
    upset, threat = rules[UPSET_CUSTOMER_RULE], rules[CUSTOMER_THREAT_RULE]
    assert upset["triggers"] == [{"trigger_type": "sentiment", "config": {"operator": "lt", "threshold": -40}}]
    assert upset["priority"] == "high" and threat["priority"] == "critical" and threat["match_logic"] == "all"
    kw = threat["triggers"][1]["config"]
    assert threat["triggers"][0]["config"] == {"operator": "lt", "threshold": -20}
    assert kw["match_logic"] == "any" and kw["keywords"] == PHRASES
    assert not any(r["enabled"] for r in rules.values())  # switched on by add_manager / activate_seat_alerts
    assert api.count("PATCH", r"/locations/[^/]+/first-alert/rules/[^/]+") == 0
    assert all(r["groups"] == [{"id": cust.manager_alerts_group_id}] for r in rules.values())
    assert api.ih_setup[cust.location_id]["group_access"] == [cust.insights_hub_group_id]
    assert api.ih_config[cust.location_id] is True
    assert cust.connector_status == "active" and cust.connector_id
    assert cust.sso_txt_record == {"name": "_ic-verify.riverbend.example.com", "value": "abc"}
    assert "company" in cust.created and not cust.existing
    # only the documented location fields: no default rule pack, no support contact
    loc_body = next(b for m, p, b in api.bodies if m == "POST" and p.endswith("/locations"))
    assert set(loc_body) == {"location_name", "street", "city", "state", "country", "zipcode", "vertical_id",
                             "enabled_products"}


def test_provision_is_idempotent(api, customer):
    before = len(api.calls)
    again = api.client().workflows.provision_seat_customer(spec())
    new_calls = api.calls[before:]
    assert not [x for x in new_calls if x[0] == "POST" and not x[1].endswith("/domains")]
    assert again.company_id == customer.company_id and again.location_id == customer.location_id
    assert again.upset_customer_rule_id == customer.upset_customer_rule_id
    assert not again.created


def test_provision_records_connector_error(api):
    api.connector_outcome = "error"
    cust = api.client().workflows.provision_seat_customer(spec(sso_domain=None))
    assert cust.connector_status == "error" and cust.connector_state_reason == "invalid_permissions"
    assert cust.upset_customer_rule_id  # the rest of the seat is still built


def test_inactive_company_needs_reactivate(api, customer):
    api.companies[customer.company_id]["is_active"] = False
    with pytest.raises(ic.InvalidRequestError):
        api.client().workflows.provision_seat_customer(spec())
    api.client().workflows.provision_seat_customer(spec(reactivate=True))
    assert api.companies[customer.company_id]["is_active"]


def test_add_frontline_user_sequence(api, customer):
    c = api.client()
    mgr = c.workflows.add_manager(customer, user(2))
    before = len(api.calls)
    fl = c.workflows.add_frontline_user(customer, user(1), "2101")
    seq = [(m, p.split("/api/v1")[-1]) for m, p in api.calls[before:]]
    writes = [(m, p) for m, p in seq if m != "GET"]
    assert [m for m, _ in writes] == ["POST", "POST", "PUT", "PUT", "PUT", "PUT", "PATCH"]
    assert writes[0][1].endswith("/users") and writes[1][1].endswith("/after-call-copilot/enable")
    assert writes[2][1].endswith("/email-preferences") and writes[3][1].endswith(f"/{fl.user_id}/connector-mappings")
    assert writes[4][1].endswith(f"/{mgr.user_id}/connector-mappings")
    assert writes[5][1].endswith("/first-alert/config") and writes[6][1].endswith("/insights-hub/setup")
    assert api.email_prefs[fl.user_id] == {"masterEnabled": False, "alerts": []}
    assert api.mappings[fl.user_id] == [{"connector_id": customer.connector_id, "monitored_numbers": ["2101"]}]
    assert api.mappings[mgr.user_id][0]["monitored_numbers"] == ["2101"]
    assert api.fa_config[customer.location_id]["connector_mappings"][0]["monitored_numbers"] == ["2101"]
    assert api.ih_setup[customer.location_id]["connector_mappings"][0]["monitored_numbers"] == ["2101"]
    assert api.users[fl.user_id]["_products"] == {"after-call-copilot"}


def test_add_manager_gets_all_lines(api, customer):
    c = api.client()
    c.workflows.add_frontline_user(customer, user(1), "2101")
    c.workflows.add_frontline_user(customer, user(3), "2103")
    mgr = c.workflows.add_manager(customer, user(2))
    assert mgr.numbers == ["2101", "2103"]
    assert api.users[mgr.user_id]["_products"] == {"after-call-copilot", "first-alert-copilot", "insights-hub"}
    groups = {g["group_name"]: g["members"] for g in api.groups.values()}
    assert mgr.user_id in groups["Manager Alerts"] and mgr.user_id in groups["Insights Hub Access"]
    prefs = api.email_prefs[mgr.user_id]
    assert prefs["masterEnabled"] and len(prefs["alerts"]) == 2 and all(a["emailEnabled"] for a in prefs["alerts"])
    assert api.fa_config[customer.location_id]["connector_mappings"][0]["monitored_numbers"] == ["2101", "2103"]
    assert [r["id"] for r in c.workflows.list_managers(customer)] == [mgr.user_id]
    assert len(c.workflows.list_frontline_users(customer)) == 2


def test_manager_mapping_is_exactly_the_end_user_lines(api, customer):
    # Base Intelligence Seat: a manager's own phone line is never captured
    c = api.client()
    c.workflows.add_frontline_user(customer, user(1), "2101")
    c.workflows.add_frontline_user(customer, user(3), "2103")
    with pytest.raises(TypeError):
        c.workflows.add_manager(customer, user(2), "2190")  # type: ignore[misc]
    mgr = c.workflows.add_manager(customer, user(2))
    lines = ["2101", "2103"]
    assert mgr.numbers == lines
    assert api.mappings[mgr.user_id] == [{"connector_id": customer.connector_id, "monitored_numbers": lines}]
    assert api.fa_config[customer.location_id]["connector_mappings"][0]["monitored_numbers"] == lines
    assert api.ih_setup[customer.location_id]["connector_mappings"][0]["monitored_numbers"] == lines


def test_add_frontline_user_is_rerunnable(api, customer):
    c = api.client()
    first = c.workflows.add_frontline_user(customer, user(1), "2101")
    again = c.workflows.add_frontline_user(customer, user(1), "2101")
    assert first.user_id == again.user_id and first.created and not again.created
    assert api.count("POST", r"/companies/[^/]+/users") == 1


def test_mapping_failure_raises_extension_mapping_error(api):
    api.connector_outcome = "error"
    c = api.client()
    cust = c.workflows.provision_seat_customer(spec(sso_domain=None))
    with pytest.raises(ic.ExtensionMappingError) as e:
        c.workflows.add_frontline_user(cust, user(1), "2101")
    assert e.value.user_id in api.users  # the user exists; re-run once the connector is active
    assert e.value.cause.status == 422
    assert not api.fa_config.get(cust.location_id)  # nothing half-synced


def test_change_user_extension(api, customer):
    c = api.client()
    fl = c.workflows.add_frontline_user(customer, user(1), "2101")
    mgr = c.workflows.add_manager(customer, user(2))
    c.workflows.change_user_extension(customer, fl.user_id, "2101", "2106")
    assert api.mappings[fl.user_id][0]["monitored_numbers"] == ["2106"]
    assert api.mappings[mgr.user_id][0]["monitored_numbers"] == ["2106"]
    assert api.fa_config[customer.location_id]["connector_mappings"][0]["monitored_numbers"] == ["2106"]
    assert api.ih_setup[customer.location_id]["connector_mappings"][0]["monitored_numbers"] == ["2106"]


def test_remove_user(api, customer):
    c = api.client()
    fl = c.workflows.add_frontline_user(customer, user(1), "2101")
    c.workflows.add_frontline_user(customer, user(3), "2103")
    mgr = c.workflows.add_manager(customer, user(2))
    c.groups.add_user_to_groups(customer.location_id, fl.user_id, [customer.insights_hub_group_id])
    out = c.workflows.remove_user(customer, fl.user_id)
    assert out["released_numbers"] == ["2101"]
    assert api.users[fl.user_id]["status"] == "deactivated"
    assert all(fl.user_id not in g["members"] for g in api.groups.values())
    assert api.mappings[fl.user_id] == []
    assert api.mappings[mgr.user_id][0]["monitored_numbers"] == ["2103"]
    assert api.fa_config[customer.location_id]["connector_mappings"][0]["monitored_numbers"] == ["2103"]
    # deactivate is last, and a second run tolerates "already deactivated"
    assert api.calls[-1][0] == "POST" and api.calls[-1][1].endswith("/deactivate")
    c.workflows.remove_user(customer, fl.user_id)


def test_remove_user_keep_extensions(api, customer):
    c = api.client()
    fl = c.workflows.add_frontline_user(customer, user(1), "2101")
    c.workflows.remove_user(customer, fl.user_id, keep_extensions=True)
    assert api.fa_config[customer.location_id]["connector_mappings"][0]["monitored_numbers"] == ["2101"]


def test_sync_numbers_dry_run_and_apply(api, customer):
    c = api.client()
    c.workflows.add_frontline_user(customer, user(1), "2101")
    mgr = c.workflows.add_manager(customer, user(2))
    # drift: First Alert lost 2101 and carries a stale 2199; the manager lost 2101 and carries
    # 2190 (their own phone, which the Seat never captures) and 2199
    c.first_alert.set_monitored_numbers(customer.location_id, customer.connector_id, ["2199"])
    c.users.set_numbers(customer.company_id, mgr.user_id, customer.connector_id, ["2190", "2199"])
    before = len(api.calls)
    diff = c.workflows.sync_numbers(customer, dry_run=True)
    assert all(m == "GET" for m, _ in api.calls[before:])
    assert diff["first_alert"] == {"add": ["2101"], "remove": ["2199"]}
    assert diff["managers"][mgr.user_id] == {"add": ["2101"], "remove": ["2190", "2199"]}
    assert diff["insights_hub"] == {"add": [], "remove": []} and not diff["applied"]
    applied = c.workflows.sync_numbers(customer)
    assert applied["applied"]
    assert api.fa_config[customer.location_id]["connector_mappings"][0]["monitored_numbers"] == ["2101"]
    assert api.mappings[mgr.user_id][0]["monitored_numbers"] == ["2101"]
    assert c.workflows.sync_numbers(customer, dry_run=True)["managers"] == {}


def test_get_seat_customer(api, customer):
    got = api.client().workflows.get_seat_customer(customer.company_id)
    for f in ("location_id", "manager_alerts_group_id", "insights_hub_group_id", "upset_customer_rule_id",
              "customer_threat_rule_id", "connector_id"):
        assert getattr(got, f) == getattr(customer, f)


def test_threat_phrases_required_for_a_new_customer(api):
    with pytest.raises(ic.InvalidRequestError) as e:
        api.client().workflows.provision_seat_customer(spec(threat_phrases=None))
    assert str(e.value) == "Customer Threat phrases are provided by your Tresic contact."
    assert not [x for x in api.calls if x[0] != "GET"]  # nothing created


def test_rerun_without_phrases_keeps_the_rule(api, customer):
    again = api.client().workflows.provision_seat_customer(spec(threat_phrases=None))
    assert again.customer_threat_rule_id == customer.customer_threat_rule_id
    kw = api.rules[customer.customer_threat_rule_id]["triggers"][1]["config"]["keywords"]
    assert kw == PHRASES


def test_rerun_with_new_phrases_updates_the_rule(api, customer):
    api.client().workflows.provision_seat_customer(spec(threat_phrases=["example phrase three"]))
    kw = api.rules[customer.customer_threat_rule_id]["triggers"][1]["config"]["keywords"]
    assert kw == ["example phrase three"]


def test_phrases_missing_when_rule_absent(api, customer):
    del api.rules[customer.customer_threat_rule_id]
    with pytest.raises(ic.InvalidRequestError):
        api.client().workflows.provision_seat_customer(spec(threat_phrases=[]))


# ---------------------------------------------------------------------- invitation and alert order


def test_users_are_created_without_an_invitation(api, customer):
    c = api.client()
    c.workflows.add_frontline_user(customer, user(1, invite=True), "2101")
    c.workflows.add_manager(customer, user(2, invite=True))
    creates = [b for m, p, b in api.bodies if m == "POST" and p.endswith("/users")]
    assert len(creates) == 2 and all(b["send_invitation"] is False for b in creates)


def test_frontline_invitation_is_the_last_write(api, customer):
    c = api.client()
    mgr = c.workflows.add_manager(customer, user(2))
    before = len(api.calls)
    fl = c.workflows.add_frontline_user(customer, user(1, invite=True), "2101")
    writes = write_paths(api, before)
    assert writes[-1] == ("POST", f"/companies/{customer.company_id}/users/{fl.user_id}/resend-invitation")
    mapping = writes.index(("PUT", f"/companies/{customer.company_id}/users/{fl.user_id}/connector-mappings"))
    assert mapping < len(writes) - 1
    assert ("PUT", f"/companies/{customer.company_id}/users/{mgr.user_id}/connector-mappings") in writes[:-1]
    assert fl.invited and api.invitations == [fl.user_id]


def test_manager_activates_alerts_then_invites(api, customer):
    c = api.client()
    c.workflows.add_frontline_user(customer, user(1), "2101")
    before = len(api.calls)
    mgr = c.workflows.add_manager(customer, user(2, invite=True))
    writes = write_paths(api, before)
    rule_patches = [i for i, (m, p) in enumerate(writes) if m == "PATCH" and "/first-alert/rules/" in p]
    mapping = writes.index(("PUT", f"/companies/{customer.company_id}/users/{mgr.user_id}/connector-mappings"))
    assert len(rule_patches) == 2 and mapping < rule_patches[0]
    assert writes[-1] == ("POST", f"/companies/{customer.company_id}/users/{mgr.user_id}/resend-invitation")
    assert all(r["enabled"] for r in api.rules.values())
    assert sorted(mgr.alerts_activated) == sorted([customer.upset_customer_rule_id, customer.customer_threat_rule_id])
    assert mgr.invited
    # a second manager finds the alerts on already
    second = c.workflows.add_manager(customer, user(3))
    assert second.alerts_activated == [] and not second.invited


def test_manager_without_alert_activation(api, customer):
    c = api.client()
    mgr = c.workflows.add_manager(customer, user(2), activate_alerts=False)
    assert mgr.alerts_activated == [] and not any(r["enabled"] for r in api.rules.values())
    switched = c.workflows.activate_seat_alerts(customer)
    assert len(switched) == 2 and all(r["enabled"] for r in api.rules.values())
    assert c.workflows.activate_seat_alerts(customer) == []


def test_send_invitation_false_never_invites(api, customer):
    c = api.client()
    c.workflows.add_frontline_user(customer, user(1), "2101")
    c.workflows.add_manager(customer, user(2))
    assert api.invitations == [] and api.count("POST", r"/companies/[^/]+/users/[^/]+/resend-invitation") == 0


def test_no_invitation_when_mapping_fails(api):
    api.connector_outcome = "error"
    c = api.client()
    cust = c.workflows.provision_seat_customer(spec(sso_domain=None))
    with pytest.raises(ic.ExtensionMappingError):
        c.workflows.add_frontline_user(cust, user(1, invite=True), "2101")
    with pytest.raises(ic.ExtensionMappingError):
        c.workflows.add_frontline_user(cust, user(3, invite=True), "2103")
    assert api.invitations == []
    # a manager whose lines cannot be mapped is not invited and does not switch the alerts on
    for u in list(api.users.values()):
        api.mappings[u["id"]] = [{"connector_id": cust.connector_id, "monitored_numbers": ["2101"]}]
        u["_products"] = {"after-call-copilot"}
    with pytest.raises(ic.ExtensionMappingError):
        c.workflows.add_manager(cust, user(2, invite=True))
    assert api.invitations == [] and not any(r["enabled"] for r in api.rules.values())


def test_rerun_after_mapping_failure_invites(api):
    api.connector_outcome = "error"
    c = api.client()
    cust = c.workflows.provision_seat_customer(spec(sso_domain=None))
    with pytest.raises(ic.ExtensionMappingError) as e:
        c.workflows.add_frontline_user(cust, user(1, invite=True), "2101")
    api.connectors[cust.connector_id]["status"] = "active"  # the connector is fixed
    again = c.workflows.add_frontline_user(cust, user(1, invite=True), "2101")
    assert again.user_id == e.value.user_id and not again.created and again.invited
    assert api.invitations == [again.user_id]


def test_rerun_keeps_rules_on(api, customer):
    c = api.client()
    c.workflows.add_manager(customer, user(2))
    c.workflows.provision_seat_customer(spec())
    assert all(r["enabled"] for r in api.rules.values())

"""Base Intelligence Seat lifecycle: provision a customer, add and remove users, keep numbers in sync.

A Seat customer is one company with one location, two alert rules ("Upset Customer", "Customer
Threat") routed to a "Manager Alerts" group, and an "Insights Hub Access" group.

- **End users** (frontline) have After Call on their own line.
- **Managers** have After Call on all lines, First Alert and Insights Hub. A manager's own phone
  line is never captured on the Seat: their mapping is exactly the end users' lines.
- **Integration users** (``add_integration_user``) read data for another system. They hold every
  line like a manager but are tagged ``department: "integration"``, are never counted as seats or
  managers, and removing one never takes a line off anyone else.

Every workflow is safe to run again. Store the returned ``company_id`` and pass it in
``SeatCustomerSpec.company_id`` on re-runs: a company is never adopted by its name alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ._base import Namespace, unwrap
from ._spec import is_uuid
from .errors import (
    ApiError,
    ConflictError,
    ConnectorError,
    ConnectorTimeoutError,
    ExtensionMappingError,
    InvalidRequestError,
    ValidationError,
)
from .resources import PRODUCT_KEYS, numbers_for

AFTER_CALL = "after-call-copilot"
FIRST_ALERT = "first-alert-copilot"
INSIGHTS_HUB = "insights-hub"
INTEGRATION_DEPARTMENT = "integration"
COMPANY_NAME_CONFLICT = "company_name_conflict"
MANAGER_ALERTS_GROUP = "Manager Alerts"
INSIGHTS_HUB_GROUP = "Insights Hub Access"
UPSET_CUSTOMER_RULE = "Upset Customer"
CUSTOMER_THREAT_RULE = "Customer Threat"
UPSET_CUSTOMER_THRESHOLD = -40
THREAT_PHRASES_MISSING = "Customer Threat phrases are provided by your Tresic contact."
CUSTOMER_THREAT_THRESHOLD = -20


def upset_customer_rule(group_ids: List[str], enabled: bool = False) -> Dict[str, Any]:
    return {
        "name": UPSET_CUSTOMER_RULE, "priority": "high", "match_logic": "any", "enabled": enabled,
        "triggers": [{"trigger_type": "sentiment", "config": {"operator": "lt", "threshold": UPSET_CUSTOMER_THRESHOLD}}],
        "group_ids": group_ids,
    }


def customer_threat_rule(group_ids: List[str], phrases: List[str], enabled: bool = False) -> Dict[str, Any]:
    """The Customer Threat alert: sentiment below -20 and any of the phrases. Phrases come from your
    Tresic contact."""
    if not phrases:
        raise InvalidRequestError(THREAT_PHRASES_MISSING)
    return {
        "name": CUSTOMER_THREAT_RULE, "priority": "critical", "match_logic": "all", "enabled": enabled,
        "triggers": [
            {"trigger_type": "sentiment", "config": {"operator": "lt", "threshold": CUSTOMER_THREAT_THRESHOLD}},
            {"trigger_type": "keyword_match", "config": {"keywords": phrases, "match_logic": "any"}},
        ],
        "group_ids": group_ids,
    }


@dataclass
class LocationSpec:
    name: str
    street: str
    city: str
    state: str
    country: str
    zipcode: str
    vertical: str  # vertical id, or its key from list_verticals (e.g. the key for service providers)


@dataclass
class ConnectorSpec:
    api_url: str  # full API root ending in /ns-api/v2
    domain: str
    api_key: str = field(repr=False)  # read/write key
    name: Optional[str] = None  # default "<location name> - NetSapiens"
    timeout: float = 600.0  # seconds to wait for the connector to settle


@dataclass
class SeatCustomerSpec:
    company_name: str
    admin_name: str  # primary contact; invited as customer admin by email
    admin_email: str
    admin_phone: str
    location: LocationSpec
    reseller_id: Optional[str] = None  # default: the signed-in reseller
    company_code: Optional[str] = None
    mfa_off: bool = False  # True for a company whose users include an integration user
    threat_phrases: Optional[List[str]] = None  # required to create the Customer Threat alert (from your Tresic contact)
    connector: Optional[ConnectorSpec] = None
    sso_domain: Optional[str] = None
    reactivate: bool = False  # reactivate a company or location found inactive
    # The company to use, from an earlier run. Without it, a company with the same name is reused only
    # when its primary contact email is admin_email; otherwise ConflictError is raised.
    company_id: Optional[str] = None


@dataclass
class SeatCustomer:
    company_id: str
    location_id: str
    manager_alerts_group_id: Optional[str] = None
    insights_hub_group_id: Optional[str] = None
    upset_customer_rule_id: Optional[str] = None
    customer_threat_rule_id: Optional[str] = None
    connector_id: Optional[str] = None
    connector_status: Optional[str] = None
    connector_state_reason: Optional[str] = None
    sso_domain_id: Optional[str] = None
    sso_txt_record: Optional[Dict[str, str]] = None  # {"name": ..., "value": ...} for the customer's DNS
    created: List[str] = field(default_factory=list)
    existing: List[str] = field(default_factory=list)
    # Users every workflow ignores (not seats, managers or integration users; their lines don't count).
    exclude_user_ids: List[str] = field(default_factory=list)
    exclude_emails: List[str] = field(default_factory=list)


@dataclass
class UserSpec:
    email: str
    first_name: str
    last_name: str
    phone_number: Optional[str] = None
    # Email the invitation once the user is fully set up (lines mapped, groups and products on).
    # False: create the user without an invitation; send one later with users.resend_invitation.
    send_invitation: bool = True
    auth_method: str = "password"


@dataclass
class SeatUser:
    user_id: str
    email: str
    kind: str  # "frontline", "manager" or "integration"
    numbers: List[str] = field(default_factory=list)
    created: bool = False
    invited: bool = False  # an invitation was emailed by this call
    alerts_activated: List[str] = field(default_factory=list)  # rule ids switched on by this call


def _products(row: Dict[str, Any]) -> set:
    return set(row.get("enabled_products") or [])


def is_integration(row: Dict[str, Any]) -> bool:
    """An integration (data-reading) user: tagged ``department: "integration"``."""
    return (row.get("department") or "").strip().lower() == INTEGRATION_DEPARTMENT


def _active_frontline(row: Dict[str, Any]) -> bool:
    return row.get("status") != "deactivated" and row.get("role") == "frontline_user"


def is_manager(row: Dict[str, Any]) -> bool:
    """A manager: all three products (After Call, First Alert, Insights Hub), not an integration user."""
    return _active_frontline(row) and not is_integration(row) and set(PRODUCT_KEYS) <= _products(row)


def is_frontline(row: Dict[str, Any]) -> bool:
    """An end user (a seat): After Call only, not an integration user."""
    return _active_frontline(row) and not is_integration(row) and _products(row) == {AFTER_CALL}


def _uniq(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for v in values:
        if v not in out:
            out.append(v)
    return out


class Workflows(Namespace):
    """Base Intelligence Seat lifecycle (admin credentials)."""

    # ------------------------------------------------------------------ provisioning

    def provision_seat_customer(self, spec: SeatCustomerSpec) -> SeatCustomer:
        c = self._c
        phrases = [p.strip() for p in (spec.threat_phrases or []) if p and p.strip()]
        created: List[str] = []
        existing: List[str] = []
        reseller_id = spec.reseller_id or unwrap(c.account.get_me()).get("reseller_id")
        if not reseller_id:
            raise InvalidRequestError("reseller_id is required (this login has none)")

        # 1. company: by id, or by name AND primary contact email; never by name alone
        company = self._find_seat_company(reseller_id, spec)
        if company is None and not phrases:
            raise InvalidRequestError(THREAT_PHRASES_MISSING)
        if company is None:
            body: Dict[str, Any] = {
                "company_name": spec.company_name,
                "primary_admin_contact_name": spec.admin_name,
                "primary_admin_contact_email": spec.admin_email,
                "primary_admin_contact_phone": spec.admin_phone,
                "enabled_products": list(PRODUCT_KEYS),
            }
            if spec.company_code:
                body["company_code"] = spec.company_code
            company = unwrap(c.companies.create_company(reseller_id, body))
            created.append("company")
        else:
            existing.append("company")
            if not company.get("is_active"):
                if not spec.reactivate:
                    raise InvalidRequestError(f"Company {spec.company_name!r} exists but is inactive "
                                              "(set reactivate=True to reactivate it)")
                c.companies.reactivate_company(company["id"])
            if not set(PRODUCT_KEYS) <= set(company.get("enabled_products") or []):
                c.companies.add_products(company["id"], PRODUCT_KEYS)
        company_id = company["id"]

        # 2. MFA off for an integration-user company, then verify
        if spec.mfa_off:
            current = unwrap(c.companies.get_company(company_id))
            if current.get("mfa_enforced"):
                c.companies.update_company(company_id, {"mfa_enforced": False})
                if unwrap(c.companies.get_company(company_id)).get("mfa_enforced"):
                    text = "MFA is still on for the company after the update"
                    raise ApiError(200, None, text, public_message=text)

        # 3. location
        loc = c.locations.find_location(company_id, spec.location.name)
        if loc is None:
            loc = unwrap(c.locations.create_location(company_id, {
                "location_name": spec.location.name, "street": spec.location.street, "city": spec.location.city,
                "state": spec.location.state, "country": spec.location.country, "zipcode": spec.location.zipcode,
                "vertical_id": self._vertical_id(spec.location.vertical),
                "enabled_products": list(PRODUCT_KEYS),
            }))
            created.append("location")
        else:
            existing.append("location")
            if not loc.get("is_active"):
                if not spec.reactivate:
                    raise InvalidRequestError(f"Location {spec.location.name!r} exists but is inactive "
                                              "(set reactivate=True to reactivate it)")
                c.locations.reactivate_location(company_id, loc["id"])
            if not set(PRODUCT_KEYS) <= set(loc.get("enabled_products") or []):
                c.locations.add_products(company_id, loc["id"], PRODUCT_KEYS)
        location_id = loc["id"]
        result = SeatCustomer(company_id=company_id, location_id=location_id, created=created, existing=existing)

        # 4. groups
        result.manager_alerts_group_id = self._ensure_group(location_id, MANAGER_ALERTS_GROUP, result)
        result.insights_hub_group_id = self._ensure_group(location_id, INSIGHTS_HUB_GROUP, result)

        # 5. rules, created disabled and routed to Manager Alerts
        groups = [result.manager_alerts_group_id]
        result.upset_customer_rule_id = self._ensure_rule(location_id, upset_customer_rule(groups), result)
        if phrases:
            threat = customer_threat_rule(groups, phrases)
        elif c.first_alert.find_rule(location_id, CUSTOMER_THREAT_RULE) is not None:
            threat = {"name": CUSTOMER_THREAT_RULE, "group_ids": groups}  # keep its configured phrases
        else:
            raise InvalidRequestError(THREAT_PHRASES_MISSING)
        result.customer_threat_rule_id = self._ensure_rule(location_id, threat, result)

        # 6. connector (optional)
        if spec.connector is not None:
            self._ensure_connector(location_id, spec, result)

        # 7. Insights Hub: group access + every call at the location
        setup = unwrap(c.insights_hub.get_insights_hub_setup(location_id)) or {}
        access = setup.get("group_access") or []
        if result.insights_hub_group_id not in access:
            if not access and not setup.get("connector_mappings"):
                c.insights_hub.save_insights_hub_setup(
                    location_id, {"connector_mappings": [], "group_access": [result.insights_hub_group_id]})
            else:
                c.insights_hub.add_groups(location_id, [result.insights_hub_group_id])
        cfg = unwrap(c.insights_hub.get_insights_hub_config(location_id)) or {}
        if not cfg.get("monitor_all_numbers"):
            c.insights_hub.update_insights_hub_config(location_id, {"monitor_all_numbers": True})

        # 8. SSO domain claim (optional): the customer publishes the TXT record, then verify
        if spec.sso_domain:
            dom = unwrap(c.sso.claim_company_domain(company_id, {"domain": spec.sso_domain})) or {}
            result.sso_domain_id = dom.get("id")
            ver = dom.get("verification") or {}
            result.sso_txt_record = {"name": ver.get("name"), "value": ver.get("value")}

        # The two rules stay off until a manager is in place: add_manager switches them on
        # (activate_alerts=True), or call activate_seat_alerts yourself.
        return result

    def _find_seat_company(self, reseller_id: str, spec: SeatCustomerSpec) -> Optional[Dict[str, Any]]:
        """The company to provision into: ``spec.company_id``, or the one company with this exact name
        whose primary contact email is ``spec.admin_email``. Raises ConflictError when the name is taken
        by any other company. Nothing has been written when it raises."""
        c = self._c
        if spec.company_id:
            return unwrap(c.companies.get_company(spec.company_id))
        same_name = c.companies.find_companies(reseller_id, spec.company_name)
        if not same_name:
            return None
        want = (spec.admin_email or "").strip().lower()
        matches = []
        for row in same_name:
            detail = unwrap(c.companies.get_company(row["id"])) or {}
            if (detail.get("primary_admin_contact_email") or "").strip().lower() == want:
                matches.append(detail)
        if len(matches) == 1:
            return matches[0]
        text = (f"A company named {spec.company_name!r} already exists with a different primary contact. "
                "Pass company_id to use an existing company, or choose a different company name.")
        raise ConflictError(409, COMPANY_NAME_CONFLICT, text, public_message=text)

    def activate_seat_alerts(self, customer: SeatCustomer) -> List[str]:
        """Switch on the customer's two alert rules (Upset Customer, Customer Threat). Rules already on
        are left as they are. Returns the ids of the rules this call switched on."""
        fa = self._c.first_alert
        switched: List[str] = []
        for rule_id in (customer.upset_customer_rule_id, customer.customer_threat_rule_id):
            if not rule_id:
                continue
            rule = unwrap(fa.get_alert_rule(customer.location_id, rule_id))
            if not rule.get("enabled"):
                fa.update_alert_rule(customer.location_id, rule_id, {"enabled": True})
                switched.append(rule_id)
        return switched

    def _vertical_id(self, vertical: str) -> str:
        if is_uuid(vertical):
            return vertical
        for v in unwrap(self._c.locations.list_verticals()) or []:
            if vertical in (v.get("key"), v.get("name")):
                return v["id"]
        raise InvalidRequestError(f"Unknown vertical {vertical!r}: use an id or key from list_verticals()")

    def _ensure_group(self, location_id: str, name: str, result: SeatCustomer) -> str:
        grp = self._c.groups.find_group(location_id, name)
        if grp is None:
            grp = unwrap(self._c.groups.create_user_group(location_id, {"group_name": name}))
            result.created.append(f"group:{name}")
        else:
            result.existing.append(f"group:{name}")
        return grp["id"]

    def _ensure_rule(self, location_id: str, body: Dict[str, Any], result: SeatCustomer) -> str:
        fa = self._c.first_alert
        found = fa.find_rule(location_id, body["name"])
        if found is None:
            rule = unwrap(fa.create_alert_rule(location_id, body))
            result.created.append(f"rule:{body['name']}")
            return rule["id"]
        result.existing.append(f"rule:{body['name']}")
        rule = unwrap(fa.get_alert_rule(location_id, found["id"]))
        have = {g["id"] for g in rule.get("groups") or []}
        if not set(body["group_ids"]) <= have:
            fa.add_rule_groups(location_id, rule["id"], body["group_ids"])
        if "triggers" in body:
            current = [{"trigger_type": t.get("trigger_type"), "config": t.get("config")} for t in rule.get("triggers") or []]
            if current != body["triggers"]:
                fa.update_alert_rule(location_id, rule["id"], {"triggers": body["triggers"]})  # e.g. a new phrase list
        return rule["id"]

    def _find_seat_connector(self, location_id: str, domain: str, name: str) -> Optional[Dict[str, Any]]:
        """The location's connector for this NetSapiens domain (best status first), else one with this
        name."""
        conns = self._c.connectors
        rank = {"active": 0, "connecting": 1, "error": 2, "deactivating": 3, "inactive": 4}
        rows = sorted(conns.iter_location_connectors(location_id), key=lambda x: rank.get(x.get("status"), 5))
        by_name = None
        for row in rows:
            detail = unwrap(conns.get_connector(location_id, row["id"])) or {}
            cfg = detail.get("config") or {}
            if (cfg.get("domain") or "").strip().lower() == domain.strip().lower():
                return detail
            if by_name is None and detail.get("name") == name:
                by_name = detail
        return by_name

    def _ensure_connector(self, location_id: str, spec: SeatCustomerSpec, result: SeatCustomer) -> None:
        cs = spec.connector
        assert cs is not None
        name = cs.name or f"{spec.location.name} - NetSapiens"
        conns = self._c.connectors
        found = self._find_seat_connector(location_id, cs.domain, name)
        if found is not None:
            cfg = found.get("config") or {}
            unchanged = (cfg.get("api_url") == cs.api_url and cfg.get("domain") == cs.domain
                         and found.get("name") == name)
            if found.get("status") in ("active", "connecting") and unchanged:
                result.existing.append("connector")
                result.connector_id = found["id"]
                result.connector_status = found.get("status")
                result.connector_state_reason = found.get("state_reason")
                return
        try:
            if found is not None:
                # In error, stopped or changed: apply the settings (and key) given now, then restart.
                result.existing.append("connector")
                result.existing.append("connector:updated")
                conns.update_connector(location_id, found["id"], {
                    "name": name, "config": {"api_url": cs.api_url, "domain": cs.domain, "api_key": cs.api_key}})
                if found.get("status") == "inactive":
                    conn = unwrap(conns.reactivate_connector(location_id, found["id"], timeout=cs.timeout))
                else:
                    conn = conns.wait_for_status(location_id, found["id"], ("active", "error"), cs.timeout,
                                                 raise_on_error=False)
                    if conn.get("status") == "error":
                        conns.deactivate_connector(location_id, found["id"], timeout=cs.timeout)
                        conn = unwrap(conns.reactivate_connector(location_id, found["id"], timeout=cs.timeout))
            else:
                conn = unwrap(conns.create_connector(location_id, {
                    "name": name, "type": "netsapiens",
                    "config": {"api_url": cs.api_url, "domain": cs.domain, "api_key": cs.api_key},
                }, timeout=cs.timeout))
                result.created.append("connector")
        except ConnectorError as exc:
            conn = exc.connector
            if found is None:
                result.created.append("connector")
        except ConnectorTimeoutError as exc:
            conn = exc.connector
            if found is None:
                result.created.append("connector")
        result.connector_id = conn.get("id")
        result.connector_status = conn.get("status")
        result.connector_state_reason = conn.get("state_reason")

    def get_seat_customer(self, company_id: str) -> SeatCustomer:
        """Rebuild the customer object (location, groups, rules, connector) from what is configured."""
        c = self._c
        locations = list(c.locations.iter_company_locations(company_id))
        if not locations:
            raise InvalidRequestError(f"Company {company_id} has no location")
        loc = next((x for x in locations if x.get("is_active")), locations[0])
        lid = loc["id"]
        result = SeatCustomer(company_id=company_id, location_id=lid)
        ma = c.groups.find_group(lid, MANAGER_ALERTS_GROUP)
        ih = c.groups.find_group(lid, INSIGHTS_HUB_GROUP)
        result.manager_alerts_group_id = ma and ma["id"]
        result.insights_hub_group_id = ih and ih["id"]
        for r in c.first_alert.iter_alert_rules(lid):
            if r.get("name") == UPSET_CUSTOMER_RULE:
                result.upset_customer_rule_id = r["id"]
            elif r.get("name") == CUSTOMER_THREAT_RULE:
                result.customer_threat_rule_id = r["id"]
        rank = {"active": 0, "connecting": 1, "error": 2, "deactivating": 3, "inactive": 4}
        conns = sorted(c.connectors.iter_location_connectors(lid), key=lambda x: rank.get(x.get("status"), 5))
        if conns and conns[0].get("status") != "inactive":
            result.connector_id = conns[0]["id"]
            result.connector_status = conns[0].get("status")
            result.connector_state_reason = conns[0].get("state_reason")
        return result

    # ------------------------------------------------------------------ users

    def _ensure_user(self, customer: SeatCustomer, user: UserSpec) -> Tuple[str, bool, Optional[str]]:
        """Find or create the user, never emailing an invitation here. Returns (id, created, status)."""
        users = self._c.users
        found = users.find_user_by_email(customer.company_id, user.email)
        if found is None:
            body: Dict[str, Any] = {
                "email": user.email, "first_name": user.first_name, "last_name": user.last_name,
                "role": "frontline_user", "location_ids": [customer.location_id],
                "send_invitation": False, "auth_method": user.auth_method,
            }
            if user.phone_number:
                body["phone_number"] = user.phone_number
            row = unwrap(users.create_company_user(customer.company_id, body))
            return row["id"], True, row.get("status") or "invited"
        uid = found["id"]
        if found.get("status") == "deactivated":
            users.reactivate_company_user(customer.company_id, uid)
        detail = unwrap(users.get_company_user(customer.company_id, uid))
        if detail.get("role") != "frontline_user":
            raise InvalidRequestError(f"{user.email} is a {detail.get('role')}; Seat users are frontline users")
        if customer.location_id not in [x["location_id"] for x in detail.get("locations") or []]:
            users.add_locations(customer.company_id, uid, [customer.location_id])
        return uid, False, detail.get("status")

    def _invite(self, customer: SeatCustomer, user: UserSpec, user_id: str, status: Optional[str]) -> bool:
        """The last step: email the invitation to a user who has not accepted one yet."""
        if not user.send_invitation or status != "invited":
            return False
        self._c.users.resend_invitation(customer.company_id, user_id)
        return True

    def _map(self, customer: SeatCustomer, user_id: str, numbers: List[str]) -> None:
        if not customer.connector_id:
            raise InvalidRequestError("This customer has no connector; numbers cannot be mapped yet")
        try:
            self._c.users.set_numbers(customer.company_id, user_id, customer.connector_id, numbers)
        except (ValidationError, ConflictError) as exc:
            raise ExtensionMappingError(user_id, exc) from exc

    def add_frontline_user(self, customer: SeatCustomer, user: UserSpec, extension: str) -> SeatUser:
        """Create an end user with After Call on their own line, and add the line to every manager,
        First Alert and Insights Hub. The invitation is emailed last, once all of that has worked
        (unless ``user.send_invitation`` is False). If the line cannot be mapped,
        ExtensionMappingError is raised and no invitation has been sent."""
        c = self._c
        ext = str(extension).strip()
        if not ext:
            raise InvalidRequestError("extension is required")
        if not customer.connector_id:
            raise InvalidRequestError("This customer has no connector; add one before adding end users")
        uid, created, status = self._ensure_user(customer, user)
        c.products.enable_user_product(customer.location_id, uid, AFTER_CALL)
        c.first_alert.set_alert_email_preferences(customer.location_id, uid, {"masterEnabled": False, "alerts": []})
        self._map(customer, uid, [ext])
        for m in self._line_holders(customer):
            if ext not in c.users.user_numbers(customer.company_id, m["id"], customer.connector_id):
                try:
                    c.users.add_numbers(customer.company_id, m["id"], customer.connector_id, [ext])
                except (ValidationError, ConflictError) as exc:
                    raise ExtensionMappingError(m["id"], exc) from exc
        c.first_alert.add_monitored_numbers(customer.location_id, customer.connector_id, [ext])
        c.insights_hub.add_numbers(customer.location_id, customer.connector_id, [ext])
        invited = self._invite(customer, user, uid, status)
        return SeatUser(user_id=uid, email=user.email, kind="frontline", numbers=[ext], created=created,
                        invited=invited)

    def add_manager(self, customer: SeatCustomer, user: UserSpec, *, activate_alerts: bool = True) -> SeatUser:
        """Create a manager: After Call on all lines, First Alert, Insights Hub, both groups, alert email on.

        The manager reads every end-user line at the location. Their own phone line is not captured
        on the Seat: it is never mapped, nor added to First Alert or Insights Hub, and a third
        positional argument raises TypeError (``activate_alerts`` is keyword-only).

        Then, with ``activate_alerts=True`` (the default), switch the customer's two alert rules on
        (see activate_seat_alerts), and last email the invitation (unless ``user.send_invitation`` is
        False). If the lines cannot be mapped, ExtensionMappingError is raised, the rules stay as they
        were and no invitation has been sent."""
        c = self._c
        uid, created, status = self._ensure_user(customer, user)
        for key in PRODUCT_KEYS:
            c.products.enable_user_product(customer.location_id, uid, key)
        groups = [g for g in (customer.manager_alerts_group_id, customer.insights_hub_group_id) if g]
        if groups:
            c.groups.add_user_to_groups(customer.location_id, uid, groups)
        prefs = c.first_alert.get_alert_notification_preferences(customer.location_id, uid) or {}
        alerts = ((prefs.get("emailNotifications") or {}).get("alerts")) or []
        c.first_alert.set_alert_email_preferences(customer.location_id, uid, {
            "masterEnabled": True, "alerts": [{"alertId": a["alertId"], "emailEnabled": True} for a in alerts]})
        numbers = self._lines(customer)
        if numbers:
            self._map(customer, uid, numbers)
        activated = self.activate_seat_alerts(customer) if activate_alerts else []
        invited = self._invite(customer, user, uid, status)
        return SeatUser(user_id=uid, email=user.email, kind="manager", numbers=numbers, created=created,
                        invited=invited, alerts_activated=activated)

    def add_integration_user(self, customer: SeatCustomer, user: UserSpec) -> SeatUser:
        """Create the customer's integration (data-reading) user: password sign-in, tagged
        ``department: "integration"``, all three products, both groups, alert email off, every line.

        It is never counted as a seat or a manager, later end users' lines are added to it, and
        ``remove_user`` on it never takes a line off anyone else. It never switches alerts on. The
        invitation (to set its password) is emailed last unless ``user.send_invitation`` is False.
        The company needs MFA off (``SeatCustomerSpec.mfa_off``) for it to sign in."""
        c = self._c
        if user.auth_method != "password":
            raise InvalidRequestError("An integration user signs in with a password: set auth_method='password'")
        uid, created, status = self._ensure_user(customer, user)
        detail = unwrap(c.users.get_company_user(customer.company_id, uid)) or {}
        if not is_integration(detail):
            c.users.update_company_user(customer.company_id, uid, {"department": INTEGRATION_DEPARTMENT})
        for key in PRODUCT_KEYS:
            c.products.enable_user_product(customer.location_id, uid, key)
        groups = [g for g in (customer.manager_alerts_group_id, customer.insights_hub_group_id) if g]
        if groups:
            c.groups.add_user_to_groups(customer.location_id, uid, groups)
        c.first_alert.set_alert_email_preferences(customer.location_id, uid, {"masterEnabled": False, "alerts": []})
        numbers = self._lines(customer)
        if numbers:
            self._map(customer, uid, numbers)
        invited = self._invite(customer, user, uid, status)
        return SeatUser(user_id=uid, email=user.email, kind="integration", numbers=numbers, created=created,
                        invited=invited)

    def change_user_extension(self, customer: SeatCustomer, user_id: str, old: str, new: str) -> Dict[str, Any]:
        """Move an end user from ``old`` to ``new``: their mapping, every manager, First Alert, Insights Hub."""
        c = self._c
        old, new = str(old).strip(), str(new).strip()
        if not customer.connector_id:
            raise InvalidRequestError("This customer has no connector")
        conn = customer.connector_id
        mine = c.users.user_numbers(customer.company_id, user_id, conn)
        self._map(customer, user_id, _uniq([new if n == old else n for n in mine] + [new]))
        for m in self._line_holders(customer):
            if m["id"] == user_id:
                continue
            cur = c.users.user_numbers(customer.company_id, m["id"], conn)
            target = _uniq([n for n in cur if n != old] + [new])
            if target != cur:
                self._map(customer, m["id"], target)
        fa = self._fa_numbers(customer)
        c.first_alert.set_monitored_numbers(customer.location_id, conn, _uniq([n for n in fa if n != old] + [new]))
        ih = self._ih_numbers(customer)
        c.insights_hub.set_numbers(customer.location_id, conn, _uniq([n for n in ih if n != old] + [new]))
        return {"user_id": user_id, "old": old, "new": new}

    def remove_user(self, customer: SeatCustomer, user_id: str, keep_extensions: bool = False) -> Dict[str, Any]:
        """Deactivate a user: they leave every group and their number mapping is cleared.

        Only an end user's line is released, and only when no other end user at the location holds
        it: it comes off managers, integration users, First Alert and Insights Hub (unless
        ``keep_extensions``). Removing a manager, an integration user, or any user holding several
        lines never takes a line off anyone else."""
        c = self._c
        conn = customer.connector_id
        rows = self._location_rows(customer, include_excluded=True)
        row = next((r for r in rows if r.get("id") == user_id), None)
        if row is None:
            row = dict(unwrap(c.users.get_location_user(customer.location_id, user_id)) or {})
            row["department"] = (unwrap(c.users.get_company_user(customer.company_id, user_id)) or {}).get("department")
        mine = c.users.user_numbers(customer.company_id, user_id, conn) if conn else []
        if is_integration(row):
            kind = "integration"
        elif set(PRODUCT_KEYS) <= _products(row):
            kind = "manager"
        elif len(mine) > 1:
            kind = "integration"  # holds several lines and is not a manager: not a seat
        else:
            kind = "frontline"
        released: List[str] = []
        if conn and kind == "frontline" and not self._excluded(customer, row):
            held_by_others = set()
            for u in self.list_frontline_users(customer):
                if u["id"] != user_id:
                    held_by_others.update(c.users.user_numbers(customer.company_id, u["id"], conn))
            released = [n for n in mine if n not in held_by_others]
        c.groups.remove_user_from_groups(customer.location_id, user_id)
        if unwrap(c.users.get_user_number_mappings(customer.company_id, user_id)):
            c.users.set_user_number_mappings(customer.company_id, user_id, {"mappings": []})
        if released and not keep_extensions:
            for m in self._line_holders(customer):
                if m["id"] == user_id:
                    continue
                cur = c.users.user_numbers(customer.company_id, m["id"], conn)
                if set(released) & set(cur):
                    self._map(customer, m["id"], [n for n in cur if n not in released])
            c.first_alert.remove_monitored_numbers(customer.location_id, conn, released)
            c.insights_hub.remove_numbers(customer.location_id, conn, released)
        try:
            c.users.deactivate_company_user(customer.company_id, user_id)
        except ConflictError:
            pass  # already deactivated
        return {"user_id": user_id, "released_numbers": [] if keep_extensions else released, "kind": kind}

    @staticmethod
    def _excluded(customer: SeatCustomer, row: Dict[str, Any]) -> bool:
        emails = {e.strip().lower() for e in customer.exclude_emails}
        return row.get("id") in customer.exclude_user_ids or (row.get("email") or "").strip().lower() in emails

    def _location_rows(self, customer: SeatCustomer, include_excluded: bool = False) -> List[Dict[str, Any]]:
        """Users at the location, each with its company-level ``department`` joined in."""
        c = self._c
        departments = {u["id"]: u.get("department")
                       for u in c.users.iter_company_users(customer.company_id, location_id=customer.location_id)}
        rows = []
        for r in c.users.iter_location_users(customer.location_id):
            row = dict(r, department=departments.get(r.get("id")))
            if include_excluded or not self._excluded(customer, row):
                rows.append(row)
        return rows

    def list_frontline_users(self, customer: SeatCustomer) -> List[Dict[str, Any]]:
        """Active end users (After Call only, not integration users) at the customer's location."""
        return [r for r in self._location_rows(customer) if is_frontline(r)]

    def list_managers(self, customer: SeatCustomer) -> List[Dict[str, Any]]:
        """Active managers (all three products, not integration users) at the customer's location."""
        return [r for r in self._location_rows(customer) if is_manager(r)]

    def list_integration_users(self, customer: SeatCustomer) -> List[Dict[str, Any]]:
        """Active integration users (tagged ``department: "integration"``) at the customer's location."""
        return [r for r in self._location_rows(customer) if _active_frontline(r) and is_integration(r)]

    def _line_holders(self, customer: SeatCustomer) -> List[Dict[str, Any]]:
        """Users who hold every line: managers and integration users."""
        return [r for r in self._location_rows(customer)
                if is_manager(r) or (_active_frontline(r) and is_integration(r))]

    # ------------------------------------------------------------------ numbers

    def _lines(self, customer: SeatCustomer) -> List[str]:
        """The location's lines: the number of every end user who holds exactly one."""
        if not customer.connector_id:
            return []
        out: List[str] = []
        for u in self.list_frontline_users(customer):
            nums = self._c.users.user_numbers(customer.company_id, u["id"], customer.connector_id)
            if len(nums) == 1:
                out = _uniq(out + nums)
        return out

    def _fa_numbers(self, customer: SeatCustomer) -> List[str]:
        cfg = unwrap(self._c.first_alert.get_first_alert_config(customer.location_id)) or {}
        return numbers_for(cfg.get("connector_mappings") or [], customer.connector_id)

    def _ih_numbers(self, customer: SeatCustomer) -> List[str]:
        setup = unwrap(self._c.insights_hub.get_insights_hub_setup(customer.location_id)) or {}
        return numbers_for(setup.get("connector_mappings") or [], customer.connector_id)

    def sync_numbers(self, customer: SeatCustomer, dry_run: bool = False) -> Dict[str, Any]:
        """Recompute the location's lines (every end user's extension) and push them to managers,
        integration users, First Alert and Insights Hub. Managers and integration users hold exactly
        the lines: any other number on their mapping is removed.
        ``dry_run=True`` returns the changes without making them."""
        c = self._c
        diff: Dict[str, Any] = {"lines": [], "managers": {}, "first_alert": {"add": [], "remove": []},
                                "insights_hub": {"add": [], "remove": []}, "applied": False}
        if not customer.connector_id:
            return diff
        conn = customer.connector_id
        lines = self._lines(customer)
        diff["lines"] = lines
        fa = self._fa_numbers(customer)
        ih = self._ih_numbers(customer)
        diff["first_alert"] = {"add": [n for n in lines if n not in fa], "remove": [n for n in fa if n not in lines]}
        diff["insights_hub"] = {"add": [n for n in lines if n not in ih], "remove": [n for n in ih if n not in lines]}
        targets: Dict[str, List[str]] = {}
        for m in self._line_holders(customer):
            cur = c.users.user_numbers(customer.company_id, m["id"], conn)
            target = list(lines)
            add = [n for n in target if n not in cur]
            remove = [n for n in cur if n not in target]
            if add or remove:
                diff["managers"][m["id"]] = {"add": add, "remove": remove}
                targets[m["id"]] = target
        if dry_run:
            return diff
        for uid, target in targets.items():
            self._map(customer, uid, target)
        if diff["first_alert"]["add"] or diff["first_alert"]["remove"]:
            c.first_alert.set_monitored_numbers(customer.location_id, conn, lines)
        if diff["insights_hub"]["add"] or diff["insights_hub"]["remove"]:
            c.insights_hub.set_numbers(customer.location_id, conn, lines)
        diff["applied"] = True
        return diff

    # ------------------------------------------------------------------ offboarding

    def offboard_customer(self, customer: SeatCustomer, deactivate_company: bool = True) -> Dict[str, Any]:
        """Stop everything for a customer who leaves, in this order: pause the After Call webhook (its
        URL is kept; it can't be deleted), clear the First Alert webhook, stop the connector (ends the
        phone-system subscription), deactivate the integration users, then deactivate the company.

        Safe to run again. Ask your Tresic contact about retention of the customer's data."""
        c = self._c
        lid = customer.location_id
        out: Dict[str, Any] = {"webhook_paused": False, "first_alert_webhook_cleared": False,
                               "connector_deactivated": False, "integration_users_deactivated": [],
                               "company_deactivated": False}
        hook = c.intelligence.get_after_call_webhook(lid) or {}
        if hook.get("webhook_url") and hook.get("enabled"):
            c.intelligence.set_after_call_webhook(lid, hook["webhook_url"], enabled=False)
            out["webhook_paused"] = True
        if c.intelligence.get_first_alert_webhook(lid):
            c.intelligence.set_first_alert_webhook(lid, None)
            out["first_alert_webhook_cleared"] = True
        if customer.connector_id:
            conn = unwrap(c.connectors.get_connector(lid, customer.connector_id)) or {}
            if conn.get("status") not in ("inactive", "deactivating"):
                try:
                    c.connectors.deactivate_connector(lid, customer.connector_id)
                except ConflictError:
                    pass  # already inactive
                out["connector_deactivated"] = True
        for u in self.list_integration_users(customer):
            try:
                c.users.deactivate_company_user(customer.company_id, u["id"])
            except ConflictError:
                continue  # already deactivated
            out["integration_users_deactivated"].append(u["id"])
        if deactivate_company:
            company = unwrap(c.companies.get_company(customer.company_id)) or {}
            if company.get("is_active", True):
                try:
                    c.companies.deactivate_company(customer.company_id)
                except ConflictError:
                    pass  # already inactive
                out["company_deactivated"] = True
        return out

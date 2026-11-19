"""Low-level resources: one method per API operation, plus read-merge-write helpers.

Every method returns the response with fields the published reference does not list removed.
List methods return a :class:`Page`; ``iter_*`` methods follow cursors for you.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import httpx

from . import _generated as g
from ._base import unwrap
from .errors import (
    ConnectorError,
    ConnectorTimeoutError,
    InvalidRequestError,
    ValidationError,
)

ResellersAPI = g.ResellersAPI
SsoAPI = g.SsoAPI
ProductsAPI = g.ProductsAPI
AfterCallSettingsAPI = g.AfterCallSettingsAPI
AccountAPI = g.AccountAPI
CallsAPI = g.CallsAPI
AlertsAPI = g.AlertsAPI
TasksAPI = g.TasksAPI
InsightsAPI = g.InsightsAPI
WebhooksAPI = g.WebhooksAPI

PRODUCT_KEYS = ("after-call-copilot", "first-alert-copilot", "insights-hub")


def _merge(existing: Iterable[str], add: Iterable[str] = (), remove: Iterable[str] = ()) -> List[str]:
    out: List[str] = []
    drop = set(remove)
    for v in list(existing) + list(add):
        if v not in out and v not in drop:
            out.append(v)
    return out


def _clean_numbers(numbers: Iterable[str]) -> List[str]:
    out: List[str] = []
    for n in numbers:
        v = str(n).strip()
        if not v:
            raise InvalidRequestError("numbers: empty entry")
        if v not in out:
            out.append(v)
    return out


def merge_mappings(mappings: Sequence[Mapping[str, Any]], connector_id: str, add: Iterable[str] = (),
                   remove: Iterable[str] = ()) -> List[Dict[str, Any]]:
    """Number mappings in request form, with numbers added to / removed from one connector."""
    out: List[Dict[str, Any]] = []
    found = False
    for m in mappings or []:
        nums = list(m.get("monitored_numbers") or [])
        if m.get("connector_id") == connector_id:
            found = True
            nums = _merge(nums, _clean_numbers(add), remove)
        if nums:
            out.append({"connector_id": m["connector_id"], "monitored_numbers": nums})
    if not found:
        nums = _merge([], _clean_numbers(add), remove)
        if nums:
            out.append({"connector_id": connector_id, "monitored_numbers": nums})
    return out


def numbers_for(mappings: Sequence[Mapping[str, Any]], connector_id: Optional[str] = None) -> List[str]:
    out: List[str] = []
    for m in mappings or []:
        if connector_id is None or m.get("connector_id") == connector_id:
            for n in m.get("monitored_numbers") or []:
                if n not in out:
                    out.append(n)
    return out


class CompaniesAPI(g.CompaniesAPI):
    def add_products(self, company_id: str, product_keys: Iterable[str]) -> Any:
        """Switch products on for the company (read, merge, PATCH)."""
        current = unwrap(self.get_company(company_id)).get("enabled_products") or []
        return self.update_company(company_id, {"enabled_products": _merge(current, product_keys)})

    def remove_products(self, company_id: str, product_keys: Iterable[str]) -> Any:
        """Switch products off for the company. At least one product must stay on."""
        current = unwrap(self.get_company(company_id)).get("enabled_products") or []
        keep = _merge(current, remove=product_keys)
        if not keep:
            raise InvalidRequestError("A company keeps at least one product; the API ignores an empty list")
        return self.update_company(company_id, {"enabled_products": keep})

    def find_company(self, reseller_id: str, company_name: str) -> Optional[Dict[str, Any]]:
        """The first company with exactly this name, or None. Names are not unique: to pick a customer,
        use its id, or ``find_companies`` and compare ``primary_admin_contact_email``."""
        found = self.find_companies(reseller_id, company_name)
        return found[0] if found else None

    def find_companies(self, reseller_id: str, company_name: str) -> List[Dict[str, Any]]:
        """Every company with exactly this name (search is a name prefix match)."""
        return [c for c in self.iter_companies(reseller_id, search=company_name)
                if c.get("company_name") == company_name]


class LocationsAPI(g.LocationsAPI):
    def add_products(self, company_id: str, location_id: str, product_keys: Iterable[str]) -> Any:
        """Switch products on at the location. They must be on for the company first."""
        current = unwrap(self.get_location(company_id, location_id)).get("enabled_products") or []
        return self.update_location(company_id, location_id, {"enabled_products": _merge(current, product_keys)})

    def remove_products(self, company_id: str, location_id: str, product_keys: Iterable[str]) -> Any:
        current = unwrap(self.get_location(company_id, location_id)).get("enabled_products") or []
        return self.update_location(company_id, location_id,
                                    {"enabled_products": _merge(current, remove=product_keys)})

    def find_location(self, company_id: str, location_name: str) -> Optional[Dict[str, Any]]:
        for loc in self.iter_company_locations(company_id, search=location_name):
            if loc.get("location_name") == location_name:
                return loc
        return None


class GroupsAPI(g.GroupsAPI):
    def add_members(self, location_id: str, group_id: str, user_ids: Iterable[str]) -> Any:
        """Add users to a group (read, merge, PATCH ``member_ids``)."""
        members = unwrap(self.get_user_group(location_id, group_id)).get("members") or []
        current = [m["id"] for m in members]
        return self.update_user_group(location_id, group_id, {"member_ids": _merge(current, user_ids)})

    def remove_members(self, location_id: str, group_id: str, user_ids: Iterable[str]) -> Any:
        members = unwrap(self.get_user_group(location_id, group_id)).get("members") or []
        current = [m["id"] for m in members]
        return self.update_user_group(location_id, group_id,
                                      {"member_ids": _merge(current, remove=user_ids)})

    def user_group_ids(self, location_id: str, user_id: str) -> List[str]:
        rows = unwrap(self.get_user_group_membership(location_id, user_id)) or []
        return [r["id"] for r in rows if r.get("is_member")]

    def add_user_to_groups(self, location_id: str, user_id: str, group_ids: Iterable[str]) -> Any:
        """Add one user to groups (read, merge, PUT the user's membership)."""
        current = self.user_group_ids(location_id, user_id)
        return self.set_user_group_membership(location_id, user_id, {"group_ids": _merge(current, group_ids)})

    def remove_user_from_groups(self, location_id: str, user_id: str,
                                group_ids: Optional[Iterable[str]] = None) -> Any:
        """Remove one user from the given groups, or from every group at the location."""
        current = self.user_group_ids(location_id, user_id)
        keep = [] if group_ids is None else _merge(current, remove=group_ids)
        return self.set_user_group_membership(location_id, user_id, {"group_ids": keep})

    def find_group(self, location_id: str, group_name: str) -> Optional[Dict[str, Any]]:
        for grp in self.iter_user_groups(location_id, search=group_name):
            if grp.get("group_name") == group_name:
                return grp
        return None


class ConnectorsAPI(g.ConnectorsAPI):
    """Create, reactivate and deactivate return at once with 202; these methods wait for the result,
    checking the connector every ``check_interval`` seconds (10) for up to ``timeout`` seconds (600)."""

    check_interval = 10.0

    def wait_for_status(self, location_id: str, connector_id: str, final: Sequence[str],
                        timeout: float = 600.0, raise_on_error: bool = True) -> Dict[str, Any]:
        start = time.monotonic()
        while True:
            conn = unwrap(self.get_connector(location_id, connector_id))
            status = conn.get("status")
            if status == "error" and raise_on_error:
                raise ConnectorError(conn)
            if status in final:
                return conn
            waited = time.monotonic() - start
            if waited >= timeout:
                raise ConnectorTimeoutError(conn, waited)
            self._c._sleep(self.check_interval)

    def create_connector(self, location_id: str, body: Mapping[str, Any], *, wait: bool = True,
                         timeout: float = 600.0) -> Any:
        """Create a connector and wait until it is ``active``. Raises ConnectorError on ``error``."""
        resp = super().create_connector(location_id, body)
        if not wait:
            return resp
        conn = unwrap(resp)
        final = self.wait_for_status(location_id, conn["id"], ("active", "error"), timeout)
        return {"data": final}

    def reactivate_connector(self, location_id: str, connector_id: str, *, wait: bool = True,
                             timeout: float = 600.0) -> Any:
        resp = super().reactivate_connector(location_id, connector_id)
        if not wait:
            return resp
        return {"data": self.wait_for_status(location_id, connector_id, ("active", "error"), timeout)}

    def deactivate_connector(self, location_id: str, connector_id: str, *, wait: bool = True,
                             timeout: float = 600.0) -> Any:
        resp = super().deactivate_connector(location_id, connector_id)
        if not wait:
            return resp
        return {"data": self.wait_for_status(location_id, connector_id, ("inactive",), timeout,
                                             raise_on_error=False)}

    def find_connector(self, location_id: str, name: str) -> Optional[Dict[str, Any]]:
        for c in self.iter_location_connectors(location_id, search=name):
            if c.get("name") == name:
                return c
        return None


class FirstAlertAPI(g.FirstAlertAPI):
    def _config(self, location_id: str) -> Dict[str, Any]:
        return unwrap(self.get_first_alert_config(location_id)) or {}

    def _save(self, location_id: str, webhook_url: Optional[str], mappings: List[Dict[str, Any]]) -> Any:
        return self.save_first_alert_config(location_id, {"webhook_url": webhook_url, "connector_mappings": mappings})

    def add_monitored_numbers(self, location_id: str, connector_id: str, numbers: Iterable[str]) -> Any:
        """Add numbers to First Alert at the location. Keeps the webhook URL and other numbers."""
        cfg = self._config(location_id)
        mappings = merge_mappings(cfg.get("connector_mappings") or [], connector_id, add=numbers)
        return self._save(location_id, cfg.get("webhook_url"), mappings)

    def remove_monitored_numbers(self, location_id: str, connector_id: str, numbers: Iterable[str]) -> Any:
        cfg = self._config(location_id)
        mappings = merge_mappings(cfg.get("connector_mappings") or [], connector_id, remove=numbers)
        return self._save(location_id, cfg.get("webhook_url"), mappings)

    def set_monitored_numbers(self, location_id: str, connector_id: str, numbers: Iterable[str]) -> Any:
        """Replace the numbers for one connector. Keeps the webhook URL and other connectors' numbers."""
        cfg = self._config(location_id)
        others = [m for m in cfg.get("connector_mappings") or [] if m.get("connector_id") != connector_id]
        mappings = merge_mappings(others, connector_id, add=numbers)
        return self._save(location_id, cfg.get("webhook_url"), mappings)

    def add_rule_groups(self, location_id: str, rule_id: str, group_ids: Iterable[str]) -> Any:
        rule = unwrap(self.get_alert_rule(location_id, rule_id))
        current = [grp["id"] for grp in rule.get("groups") or []]
        return self.update_alert_rule(location_id, rule_id, {"group_ids": _merge(current, group_ids)})

    def remove_rule_groups(self, location_id: str, rule_id: str, group_ids: Iterable[str]) -> Any:
        rule = unwrap(self.get_alert_rule(location_id, rule_id))
        current = [grp["id"] for grp in rule.get("groups") or []]
        return self.update_alert_rule(location_id, rule_id, {"group_ids": _merge(current, remove=group_ids)})

    def find_rule(self, location_id: str, name: str) -> Optional[Dict[str, Any]]:
        for r in self.iter_alert_rules(location_id):
            if r.get("name") == name:
                return r
        return None


class InsightsHubAPI(g.InsightsHubAPI):
    def _setup(self, location_id: str) -> Dict[str, Any]:
        return unwrap(self.get_insights_hub_setup(location_id)) or {}

    def add_numbers(self, location_id: str, connector_id: str, numbers: Iterable[str]) -> Any:
        """Add numbers to the location's Insights Hub (read, merge, PATCH ``connector_mappings``)."""
        setup = self._setup(location_id)
        mappings = merge_mappings(setup.get("connector_mappings") or [], connector_id, add=numbers)
        return self.update_insights_hub_setup(location_id, {"connector_mappings": mappings})

    def remove_numbers(self, location_id: str, connector_id: str, numbers: Iterable[str]) -> Any:
        setup = self._setup(location_id)
        mappings = merge_mappings(setup.get("connector_mappings") or [], connector_id, remove=numbers)
        return self.update_insights_hub_setup(location_id, {"connector_mappings": mappings})

    def set_numbers(self, location_id: str, connector_id: str, numbers: Iterable[str]) -> Any:
        setup = self._setup(location_id)
        others = [m for m in setup.get("connector_mappings") or [] if m.get("connector_id") != connector_id]
        return self.update_insights_hub_setup(
            location_id, {"connector_mappings": merge_mappings(others, connector_id, add=numbers)})

    def add_groups(self, location_id: str, group_ids: Iterable[str]) -> Any:
        """Give groups Insights Hub access (read, merge, PATCH ``group_access``)."""
        current = self._setup(location_id).get("group_access") or []
        return self.update_insights_hub_setup(location_id, {"group_access": _merge(current, group_ids)})

    def remove_groups(self, location_id: str, group_ids: Iterable[str]) -> Any:
        current = self._setup(location_id).get("group_access") or []
        return self.update_insights_hub_setup(location_id, {"group_access": _merge(current, remove=group_ids)})


class UsersAPI(g.UsersAPI):
    def create_company_user(self, company_id: str, body: Mapping[str, Any], *,
                            idempotency_key: Optional[str] = None) -> Any:
        """Create a user. Sends an ``Idempotency-Key`` (reused on retries).

        A 422 can leave the user behind; the SDK then finds the user by email and applies
        ``location_ids`` with PATCH. The response never includes the one-time sign-in link.
        """
        key = idempotency_key or str(uuid.uuid4())
        email = body.get("email") if isinstance(body, Mapping) else None
        try:
            return self._c._call("createCompanyUser", path={"companyId": company_id}, query={}, body=body,
                                 headers={"Idempotency-Key": key})
        except ValidationError as exc:
            if exc.status != 422 or not email:
                raise
            user = self.find_user_by_email(company_id, email)
            if user is None:
                raise
            if body.get("location_ids"):
                self.update_company_user(company_id, user["id"], {"location_ids": list(body["location_ids"])})
            return self.get_company_user(company_id, user["id"])
        except httpx.DecodingError:
            # A replayed create can come back with a body that cannot be decoded: read the user instead.
            user = self.find_user_by_email(company_id, email) if email else None
            if user is None:
                raise
            return self.get_company_user(company_id, user["id"])

    def find_user_by_email(self, company_id: str, email: str) -> Optional[Dict[str, Any]]:
        want = email.strip().lower()
        for u in self.iter_company_users(company_id, search=email.strip()):
            if (u.get("email") or "").lower() == want:
                return u
        return None

    def add_locations(self, company_id: str, user_id: str, location_ids: Iterable[str]) -> Any:
        user = unwrap(self.get_company_user(company_id, user_id))
        current = [loc["location_id"] for loc in user.get("locations") or []]
        return self.update_company_user(company_id, user_id, {"location_ids": _merge(current, location_ids)})

    def remove_locations(self, company_id: str, user_id: str, location_ids: Iterable[str]) -> Any:
        user = unwrap(self.get_company_user(company_id, user_id))
        current = [loc["location_id"] for loc in user.get("locations") or []]
        return self.update_company_user(company_id, user_id,
                                        {"location_ids": _merge(current, remove=location_ids)})

    def user_numbers(self, company_id: str, user_id: str, connector_id: Optional[str] = None) -> List[str]:
        return numbers_for(unwrap(self.get_user_number_mappings(company_id, user_id)) or [], connector_id)

    def add_numbers(self, company_id: str, user_id: str, connector_id: str, numbers: Iterable[str]) -> Any:
        """Map numbers to the user (read, merge, PUT). The connector must be ``active``."""
        current = unwrap(self.get_user_number_mappings(company_id, user_id)) or []
        return self.set_user_number_mappings(
            company_id, user_id, {"mappings": merge_mappings(current, connector_id, add=numbers)})

    def remove_numbers(self, company_id: str, user_id: str, connector_id: str, numbers: Iterable[str]) -> Any:
        current = unwrap(self.get_user_number_mappings(company_id, user_id)) or []
        return self.set_user_number_mappings(
            company_id, user_id, {"mappings": merge_mappings(current, connector_id, remove=numbers)})

    def set_numbers(self, company_id: str, user_id: str, connector_id: str, numbers: Iterable[str]) -> Any:
        """Replace the user's numbers on one connector; other connectors are kept."""
        current = unwrap(self.get_user_number_mappings(company_id, user_id)) or []
        others = [m for m in current if m.get("connector_id") != connector_id]
        return self.set_user_number_mappings(
            company_id, user_id, {"mappings": merge_mappings(others, connector_id, add=numbers)})

"""An in-memory stand-in for the API, used through httpx.MockTransport. No network."""
from __future__ import annotations

import json
import re
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

import intelligence_cloud as ic

RESELLER = "00000000-0000-4000-8000-0000000000aa"
VERTICAL = "00000000-0000-4000-8000-0000000000bb"


def new_id() -> str:
    return str(uuid.uuid4())


def res(type_: str, attrs: Dict[str, Any]) -> Dict[str, Any]:
    return {"data": {"type": type_, "attributes": attrs}}


def page(rows: List[Dict[str, Any]], type_: Optional[str] = None) -> Dict[str, Any]:
    data = [{"type": type_, "attributes": r} for r in rows] if type_ else rows
    return {"data": data, "pagination": {"has_more": False, "next_cursor": None, "total_count": len(rows)}}


class FakeAPI:
    """Stateful fake. ``calls`` logs (METHOD, path) for every request after sign-in."""

    def __init__(self, connector_outcome: str = "active", role: str = "reseller_admin"):
        self.calls: List[Tuple[str, str]] = []
        self.bodies: List[Tuple[str, str, Any]] = []
        self.connector_outcome = connector_outcome
        self.role = role
        self.companies: Dict[str, Dict[str, Any]] = {}
        self.locations: Dict[str, Dict[str, Any]] = {}
        self.groups: Dict[str, Dict[str, Any]] = {}
        self.rules: Dict[str, Dict[str, Any]] = {}
        self.connectors: Dict[str, Dict[str, Any]] = {}
        self.ih_setup: Dict[str, Dict[str, Any]] = {}
        self.ih_config: Dict[str, bool] = {}
        self.fa_config: Dict[str, Dict[str, Any]] = {}
        self.users: Dict[str, Dict[str, Any]] = {}
        self.mappings: Dict[str, List[Dict[str, Any]]] = {}
        self.email_prefs: Dict[str, Dict[str, Any]] = {}
        self.invitations: List[str] = []  # user ids emailed an invitation, in order
        self.after_call_hooks: Dict[str, Dict[str, Any]] = {}
        self.routes: List[Tuple[str, re.Pattern, Callable]] = []
        self._register()

    # ------------------------------------------------------------------ plumbing
    def client(self, **kw) -> ic.Client:
        kw.setdefault("sleep", lambda s: None)
        return ic.Client(email="integration@example.com", password="pw", transport=httpx.MockTransport(self), **kw)

    def route(self, method: str, pattern: str):
        def deco(fn):
            self.routes.append((method, re.compile("^/api/v1" + pattern + "$"), fn))
            return fn
        return deco

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        if path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "A", "refresh_token": "R", "token_type": "Bearer",
                                             "expires_in": 899, "user": {"id": new_id(), "role": self.role}})
        self.calls.append((request.method, path))
        self.bodies.append((request.method, path, body))
        for method, rx, fn in self.routes:
            m = rx.match(path)
            if m and method == request.method:
                out = fn(request, body, *m.groups())
                if isinstance(out, httpx.Response):
                    return out
                status, payload = out
                return httpx.Response(status, json=payload) if payload is not None else httpx.Response(status)
        return httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": f"no route {path}"}})

    def count(self, method: str, pattern: str) -> int:
        rx = re.compile("^/api/v1" + pattern + "$")
        return sum(1 for m, p in self.calls if m == method and rx.match(p))

    def location_users(self, lid: str) -> List[Dict[str, Any]]:
        return [u for u in self.users.values() if lid in u["_locations"]]

    # ------------------------------------------------------------------ routes
    def _register(self) -> None:  # noqa: C901 - a fake server is a long switch
        api = self

        @self.route("GET", r"/me")
        def me(req, body):
            return 200, {"data": {"id": new_id(), "role": api.role, "reseller_id": RESELLER,
                                  "user_type": "reseller_user", "unexpected_field": "redacted"}}

        @self.route("GET", r"/verticals")
        def verticals(req, body):
            return 200, {"data": [{"id": VERTICAL, "key": "service-providers", "name": "Service providers"}]}

        # companies
        @self.route("GET", r"/resellers/([^/]+)/companies")
        def list_companies(req, body, rid):
            q = req.url.params.get("search", "")
            rows = [c for c in api.companies.values() if c["company_name"].lower().startswith(q.lower())]
            return 200, {"data": [{"type": "company", "attributes": c} for c in rows], "has_more": False,
                         "next_cursor": None, "total_count": len(rows)}

        @self.route("POST", r"/resellers/([^/]+)/companies")
        def create_company(req, body, rid):
            cid = new_id()
            c = dict(body, id=cid, reseller_id=rid, is_active=True, mfa_enforced=True)
            api.companies[cid] = c
            return 201, {"data": {"type": "company", "attributes": c},
                         "invited_user": {"id": new_id(), "email": body["primary_admin_contact_email"]}}

        @self.route("GET", r"/companies/([^/]+)")
        def get_company(req, body, cid):
            return (200, res("company", api.companies[cid])) if cid in api.companies else (404, {"error": {}})

        @self.route("PATCH", r"/companies/([^/]+)")
        def patch_company(req, body, cid):
            api.companies[cid].update(body)
            return 200, res("company", api.companies[cid])

        @self.route("POST", r"/companies/([^/]+)/deactivate")
        def deact_company(req, body, cid):
            if not api.companies[cid]["is_active"]:
                return 409, {"error": {"code": "CONFLICT", "message": "Company is already inactive"}}
            api.companies[cid]["is_active"] = False
            return 200, res("company", api.companies[cid])

        @self.route("GET", r"/locations/([^/]+)/after-call/automation")
        def get_hook(req, body, lid):
            return 200, {"data": api.after_call_hooks.get(lid)}

        @self.route("PUT", r"/locations/([^/]+)/after-call/automation")
        def put_hook(req, body, lid):
            api.after_call_hooks[lid] = {"webhook_url": body["webhook_url"], "enabled": body.get("enabled", True)}
            return 200, {"data": api.after_call_hooks[lid]}

        @self.route("POST", r"/companies/([^/]+)/reactivate")
        def react_company(req, body, cid):
            api.companies[cid]["is_active"] = True
            return 200, res("company", api.companies[cid])

        @self.route("POST", r"/companies/([^/]+)/domains")
        def claim(req, body, cid):
            return 201, {"data": {"id": "dom-1", "domain": body["domain"], "status": "pending",
                                  "verification": {"type": "TXT", "name": "_ic-verify." + body["domain"], "value": "abc"}}}

        # locations
        @self.route("GET", r"/companies/([^/]+)/locations")
        def list_locations(req, body, cid):
            q = req.url.params.get("search", "")
            rows = [x for x in api.locations.values() if x["company_id"] == cid and q.lower() in x["location_name"].lower()]
            return 200, page(rows, "location")

        @self.route("POST", r"/companies/([^/]+)/locations")
        def create_location(req, body, cid):
            lid = new_id()
            api.locations[lid] = dict(body, id=lid, company_id=cid, is_active=True)
            return 201, res("location", api.locations[lid])

        @self.route("GET", r"/companies/([^/]+)/locations/([^/]+)")
        def get_location(req, body, cid, lid):
            return 200, res("location", api.locations[lid])

        @self.route("PATCH", r"/companies/([^/]+)/locations/([^/]+)")
        def patch_location(req, body, cid, lid):
            api.locations[lid].update(body)
            return 200, res("location", api.locations[lid])

        # groups
        @self.route("GET", r"/locations/([^/]+)/user-groups")
        def list_groups(req, body, lid):
            q = req.url.params.get("search", "")
            rows = [{k: v for k, v in g.items() if k != "members"} for g in api.groups.values()
                    if g["location_id"] == lid and q.lower() in g["group_name"].lower()]
            return 200, page(rows, "user_group")

        @self.route("POST", r"/locations/([^/]+)/user-groups")
        def create_group(req, body, lid):
            gid = new_id()
            api.groups[gid] = {"id": gid, "location_id": lid, "group_name": body["group_name"], "members": []}
            return 201, res("user_group", api.groups[gid])

        @self.route("GET", r"/locations/([^/]+)/user-groups/([^/]+)")
        def get_group(req, body, lid, gid):
            g = api.groups[gid]
            return 200, res("user_group", dict(g, members=[{"id": m} for m in g["members"]]))

        @self.route("GET", r"/locations/([^/]+)/users/([^/]+)/group-membership")
        def get_membership(req, body, lid, uid):
            return 200, {"data": [{"id": g["id"], "name": g["group_name"], "is_member": uid in g["members"]}
                                  for g in api.groups.values() if g["location_id"] == lid]}

        @self.route("PUT", r"/locations/([^/]+)/users/([^/]+)/group-membership")
        def put_membership(req, body, lid, uid):
            for g in api.groups.values():
                if g["location_id"] != lid:
                    continue
                if g["id"] in body["group_ids"] and uid not in g["members"]:
                    g["members"].append(uid)
                if g["id"] not in body["group_ids"] and uid in g["members"]:
                    g["members"].remove(uid)
            return get_membership(req, None, lid, uid)

        # rules
        @self.route("GET", r"/locations/([^/]+)/first-alert/rules")
        def list_rules(req, body, lid):
            rows = [{k: v for k, v in r.items() if k != "triggers"} for r in api.rules.values() if r["location_id"] == lid]
            return 200, page(rows, "first_alert_rule")

        @self.route("POST", r"/locations/([^/]+)/first-alert/rules")
        def create_rule(req, body, lid):
            rid = new_id()
            r = dict(body, id=rid, location_id=lid, groups=[{"id": g} for g in body.get("group_ids", [])])
            r.pop("group_ids", None)
            api.rules[rid] = r
            return 201, res("first_alert_rule", r)

        @self.route("GET", r"/locations/([^/]+)/first-alert/rules/([^/]+)")
        def get_rule(req, body, lid, rid):
            return 200, res("first_alert_rule", api.rules[rid])

        @self.route("PATCH", r"/locations/([^/]+)/first-alert/rules/([^/]+)")
        def patch_rule(req, body, lid, rid):
            body = dict(body)
            if "group_ids" in body:
                api.rules[rid]["groups"] = [{"id": g} for g in body.pop("group_ids")]
            api.rules[rid].update(body)
            return 200, res("first_alert_rule", api.rules[rid])

        # connectors
        @self.route("GET", r"/locations/([^/]+)/connectors")
        def list_conns(req, body, lid):
            rows = [{k: v for k, v in c.items() if k != "config"} for c in api.connectors.values() if c["location_id"] == lid]
            return 200, page(rows)

        @self.route("POST", r"/locations/([^/]+)/connectors")
        def create_conn(req, body, lid):
            cid = new_id()
            api.connectors[cid] = {"id": cid, "location_id": lid, "name": body["name"], "type": body["type"],
                                   "status": "connecting", "_polls": 0,
                                   "config": {"api_url": body["config"]["api_url"], "domain": body["config"]["domain"],
                                              "unexpected_field": "redacted"}}
            return 202, {"data": api.connectors[cid]}

        @self.route("GET", r"/locations/([^/]+)/connectors/([^/]+)")
        def get_conn(req, body, lid, cid):
            c = api.connectors[cid]
            c["_polls"] += 1
            if c["status"] == "connecting" and c["_polls"] >= 2:
                c["status"] = api.connector_outcome
                if c["status"] == "error":
                    c["state_reason"] = "invalid_permissions"
                    c["status_message"] = "The key was refused."
            if c["status"] == "deactivating":
                c["status"] = "inactive"
            return 200, {"data": c}

        @self.route("PATCH", r"/locations/([^/]+)/connectors/([^/]+)")
        def patch_conn(req, body, lid, cid):
            c = api.connectors[cid]
            if "name" in body:
                c["name"] = body["name"]
            if "config" in body:
                c["config"].update(api_url=body["config"]["api_url"], domain=body["config"]["domain"])
                c["_key"] = body["config"]["api_key"]
            return 200, {"data": c}

        @self.route("POST", r"/locations/([^/]+)/connectors/([^/]+)/deactivate")
        def deact_conn(req, body, lid, cid):
            api.connectors[cid]["status"] = "deactivating"
            return 202, {"data": api.connectors[cid]}

        @self.route("POST", r"/locations/([^/]+)/connectors/([^/]+)/reactivate")
        def react_conn(req, body, lid, cid):
            api.connectors[cid].update(status="connecting", _polls=0)
            return 202, {"data": api.connectors[cid]}

        # Insights Hub
        @self.route("GET", r"/locations/([^/]+)/insights-hub/setup")
        def get_ih(req, body, lid):
            s = api.ih_setup.get(lid, {"connector_mappings": [], "group_access": []})
            return 200, {"data": {"type": "insights_hub_setup", "attributes": s}}

        @self.route("POST", r"/locations/([^/]+)/insights-hub/setup")
        def post_ih(req, body, lid):
            api.ih_setup[lid] = {"connector_mappings": body["connector_mappings"], "group_access": body["group_access"]}
            return 201, {"data": {"type": "insights_hub_setup", "attributes": api.ih_setup[lid]}}

        @self.route("PATCH", r"/locations/([^/]+)/insights-hub/setup")
        def patch_ih(req, body, lid):
            s = api.ih_setup.setdefault(lid, {"connector_mappings": [], "group_access": []})
            s.update(body)
            return 200, {"data": {"type": "insights_hub_setup", "attributes": s}}

        @self.route("GET", r"/locations/([^/]+)/insights-hub/config")
        def get_ihc(req, body, lid):
            return 200, {"data": {"type": "insights_hub_config",
                                  "attributes": {"monitor_all_numbers": api.ih_config.get(lid, False)}}}

        @self.route("PATCH", r"/locations/([^/]+)/insights-hub/config")
        def patch_ihc(req, body, lid):
            api.ih_config[lid] = body["monitor_all_numbers"]
            return get_ihc(req, None, lid)

        # First Alert config
        @self.route("GET", r"/locations/([^/]+)/first-alert/config")
        def get_fa(req, body, lid):
            return 200, {"data": api.fa_config.get(lid, {"webhook_url": None, "connector_mappings": []})}

        @self.route("PUT", r"/locations/([^/]+)/first-alert/config")
        def put_fa(req, body, lid):
            api.fa_config[lid] = {"webhook_url": body.get("webhook_url"),
                                  "connector_mappings": [dict(m, id=new_id()) for m in body["connector_mappings"]]}
            return get_fa(req, None, lid)

        # users
        @self.route("GET", r"/companies/([^/]+)/users")
        def list_users(req, body, cid):
            q = (req.url.params.get("search") or "").lower()
            lid = req.url.params.get("location_id")
            rows = [api._user_attrs(u) for u in api.users.values() if u["company_id"] == cid and q in u["email"].lower()
                    and (not lid or lid in u["_locations"])]
            return 200, page(rows, "company_user")

        @self.route("POST", r"/companies/([^/]+)/users")
        def create_user(req, body, cid):
            assert req.headers.get("Idempotency-Key")
            uid = new_id()
            api.users[uid] = {"id": uid, "company_id": cid, "email": body["email"], "role": body["role"],
                              "status": "invited", "_locations": list(body.get("location_ids", [])), "_products": set()}
            if body.get("send_invitation"):
                api.invitations.append(uid)
            return 201, {"data": {"type": "company_user", "attributes": api._user_attrs(api.users[uid])},
                         "meta": {"invitation_link": "https://app.example.com/accept?token=SECRET"}}

        @self.route("GET", r"/companies/([^/]+)/users/([^/]+)")
        def get_user(req, body, cid, uid):
            return 200, {"data": {"type": "company_user", "attributes": api._user_attrs(api.users[uid])}}

        @self.route("PATCH", r"/companies/([^/]+)/users/([^/]+)")
        def patch_user(req, body, cid, uid):
            if "location_ids" in body:
                api.users[uid]["_locations"] = list(body["location_ids"])
            if "department" in body:
                api.users[uid]["department"] = body["department"]
            return get_user(req, None, cid, uid)

        @self.route("POST", r"/companies/([^/]+)/users/([^/]+)/deactivate")
        def deact_user(req, body, cid, uid):
            if api.users[uid]["status"] == "deactivated":
                return 409, {"error": {"code": "CONFLICT", "message": "User is already deactivated"}}
            api.users[uid]["status"] = "deactivated"
            return get_user(req, None, cid, uid)

        @self.route("POST", r"/companies/([^/]+)/users/([^/]+)/resend-invitation")
        def resend(req, body, cid, uid):
            if api.users[uid]["status"] != "invited":
                return 409, {"error": {"code": "CONFLICT", "message": "User does not have a pending invitation"}}
            api.invitations.append(uid)
            return 202, {"data": {"type": "invitation_resend", "attributes": {"user_id": uid,
                                                                             "email": api.users[uid]["email"]}}}

        @self.route("POST", r"/companies/([^/]+)/users/([^/]+)/reactivate")
        def react_user(req, body, cid, uid):
            api.users[uid]["status"] = "active"
            return get_user(req, None, cid, uid)

        @self.route("GET", r"/companies/([^/]+)/users/([^/]+)/connector-mappings")
        def get_maps(req, body, cid, uid):
            return 200, {"data": api.mappings.get(uid, [])}

        @self.route("PUT", r"/companies/([^/]+)/users/([^/]+)/connector-mappings")
        def put_maps(req, body, cid, uid):
            for m in body["mappings"]:
                if api.connectors.get(m["connector_id"], {}).get("status") != "active":
                    return 422, {"error": {"code": "VALIDATION_ERROR", "message": "connector not found or inactive"}}
            api.mappings[uid] = body["mappings"]
            return 200, {"data": body["mappings"]}

        @self.route("GET", r"/locations/([^/]+)/users")
        def list_loc_users(req, body, lid):
            return 200, page([api._loc_user(u, lid) for u in api.location_users(lid)], "location_user")

        @self.route("GET", r"/locations/([^/]+)/users/([^/]+)")
        def get_loc_user(req, body, lid, uid):
            return 200, {"data": {"type": "location_user", "attributes": api._loc_user(api.users[uid], lid)}}

        @self.route("POST", r"/locations/([^/]+)/users/([^/]+)/products/([^/]+)/enable")
        def enable(req, body, lid, uid, key):
            api.users[uid]["_products"].add(key)
            return 200, {"data": {"product_key": key, "enabled": True}}

        @self.route("PUT", r"/locations/([^/]+)/users/([^/]+)/first-alert/email-preferences")
        def email_prefs(req, body, lid, uid):
            api.email_prefs[uid] = body
            return 200, {"emailNotifications": {"masterEnabled": body["masterEnabled"], "alerts": []}}

        @self.route("GET", r"/locations/([^/]+)/users/([^/]+)/first-alert/notification-preferences")
        def get_prefs(req, body, lid, uid):
            alerts = [{"alertId": r["id"], "alertName": r["name"], "emailEnabled": False}
                      for r in api.rules.values() if r["location_id"] == lid]
            return 200, {"emailNotifications": {"masterEnabled": False, "alerts": alerts},
                         "digest": {"enabled": False}, "webhook": {"url": None}}

    def _user_attrs(self, u: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": u["id"], "company_id": u["company_id"], "email": u["email"], "role": u["role"],
                "status": u["status"], "locations": [{"location_id": x} for x in u["_locations"]],
                **({"department": u["department"]} if u.get("department") else {})}

    def _loc_user(self, u: Dict[str, Any], lid: str) -> Dict[str, Any]:
        return {"id": u["id"], "email": u["email"], "role": u["role"], "status": u["status"], "location_id": lid,
                "enabled_products": sorted(u["_products"]),
                "groups": [g["group_name"] for g in self.groups.values() if u["id"] in g["members"]]}

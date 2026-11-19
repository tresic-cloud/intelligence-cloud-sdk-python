"""Regenerate the operation registry and the low-level resource classes from openapi.yaml.

    uv run --with pyyaml python tools/generate.py path/to/openapi.yaml [--check]

Writes:
  src/intelligence_cloud/data/spec.json   operations, query filters, body schemas, response schemas
  src/intelligence_cloud/_generated.py    one class per spec tag, one method per operation

Download openapi.yaml from https://docs.intelligence.cloud/openapi.yaml.
``--check`` writes nothing and exits 1 when either file differs from what the spec generates.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent.parent
OUT_JSON = HERE / "src" / "intelligence_cloud" / "data" / "spec.json"
OUT_PY = HERE / "src" / "intelligence_cloud" / "_generated.py"

TAGS = {
    "Authentication": ("auth", "AuthAPI"),
    "Resellers": ("resellers", "ResellersAPI"),
    "Companies": ("companies", "CompaniesAPI"),
    "Single sign-on": ("sso", "SsoAPI"),
    "Products": ("products", "ProductsAPI"),
    "Locations": ("locations", "LocationsAPI"),
    "User groups": ("groups", "GroupsAPI"),
    "Connectors": ("connectors", "ConnectorsAPI"),
    "First Alert": ("first_alert", "FirstAlertAPI"),
    "Insights Hub": ("insights_hub", "InsightsHubAPI"),
    "Users": ("users", "UsersAPI"),
    "After Call settings": ("after_call_settings", "AfterCallSettingsAPI"),
    "Account": ("account", "AccountAPI"),
    "Calls": ("calls", "CallsAPI"),
    "Alerts": ("alerts", "AlertsAPI"),
    "Tasks": ("tasks", "TasksAPI"),
    "Insights": ("insights", "InsightsAPI"),
    "Events and webhooks": ("webhooks", "WebhooksAPI"),
}
KEEP = {"type", "properties", "items", "oneOf", "anyOf", "allOf", "additionalProperties", "$ref", "required"}


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def compact(x):
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if k == "properties":
                out[k] = {pk: compact(pv) for pk, pv in v.items()}
            elif k in KEEP:
                out[k] = compact(v)
        return out
    if isinstance(x, list):
        return [compact(i) for i in x]
    return x


def ref_name(r: str) -> str:
    return r.split("/")[-1]


def main(spec_path: pathlib.Path, check: bool = False) -> int:
    spec = yaml.safe_load(spec_path.read_text())
    comps = spec["components"]
    schemas = {k: compact(v) for k, v in comps["schemas"].items()}

    def resolve_param(p):
        return comps["parameters"][ref_name(p["$ref"])] if "$ref" in p else p

    def resolve_schema(s):
        while isinstance(s, dict) and "$ref" in s:
            s = comps["schemas"][ref_name(s["$ref"])]
        return s

    ops = {}
    for path, item in spec["paths"].items():
        shared = item.get("parameters", [])
        for method, op in item.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            params = [resolve_param(p) for p in shared + op.get("parameters", [])]
            query = {}
            path_params = []
            headers = []
            for p in params:
                if p["in"] == "path":
                    path_params.append(p["name"])
                elif p["in"] == "header":
                    headers.append(p["name"])
                elif p["in"] == "query":
                    sch = resolve_schema(p.get("schema", {}))
                    q = {"type": sch.get("type", "string"), "required": bool(p.get("required"))}
                    for key in ("format", "enum", "minimum", "maximum", "maxItems"):
                        if key in sch:
                            q[key] = sch[key]
                    if q["type"] == "array":
                        items = resolve_schema(sch.get("items", {}))
                        q["items"] = {k: items[k] for k in ("format", "pattern", "type") if k in items}
                    if q["type"] == "string" and "enum" in sch and "format" not in q:
                        pass
                    query[p["name"]] = q
            # path params in path order
            order = re.findall(r"{(\w+)}", path)
            path_params = sorted(set(path_params), key=order.index)
            body = None
            rb = op.get("requestBody")
            if rb:
                sch = rb["content"]["application/json"]["schema"]
                body = {"schema": compact(sch), "required": bool(rb.get("required"))}
            responses = {}
            for status, r in op.get("responses", {}).items():
                if "$ref" in r:
                    continue
                c = r.get("content", {}).get("application/json")
                if c and "schema" in c and status.startswith("2"):
                    responses[status] = compact(c["schema"])
                elif status.startswith("2"):
                    responses[status] = None
            ns, _cls = TAGS[op["tags"][0]]
            ops[op["operationId"]] = {
                "method": method.upper(),
                "path": path,
                "namespace": ns,
                "path_params": path_params,
                "headers": headers,
                "query": query,
                "body": body,
                "responses": responses,
                "summary": op.get("summary", ""),
                "role": op.get("x-required-role", ""),
                "paged": "cursor" in query,
            }

    webhooks = {name: compact(w["post"]["requestBody"]["content"]["application/json"]["schema"])
                for name, w in spec.get("webhooks", {}).items()}
    out_json = json.dumps({"schemas": schemas, "operations": ops, "webhooks": webhooks},
                          indent=1, sort_keys=True) + "\n"
    out_py = render(ops)
    if check:
        stale = [p.name for p, text in ((OUT_JSON, out_json), (OUT_PY, out_py))
                 if not p.exists() or p.read_text() != text]
        print("up to date" if not stale else f"out of date: {', '.join(stale)}")
        return 1 if stale else 0
    OUT_JSON.write_text(out_json)
    OUT_PY.write_text(out_py)
    print(f"{len(ops)} operations -> {OUT_JSON.name}, {OUT_PY.name}")
    return 0


PY_TYPES = {"string": "str", "integer": "int", "boolean": "bool", "number": "float"}


def qtype(q) -> str:
    if q["type"] == "array":
        return "Union[str, Sequence[str]]"
    if q.get("format") in ("date-time",):
        return "Union[str, datetime]"
    if q.get("format") == "date":
        return "Union[str, date]"
    if q.get("enum") == ["true"]:
        return "bool"
    return PY_TYPES.get(q["type"], "Any")


def render(ops) -> str:
    by_ns = {}
    for op_id, op in ops.items():
        by_ns.setdefault(op["namespace"], []).append((op_id, op))
    lines = [
        '"""Generated from openapi.yaml by tools/generate.py. Do not edit by hand."""',
        "# flake8: noqa",
        "from __future__ import annotations",
        "",
        "from datetime import date, datetime",
        "from typing import Any, Iterator, Mapping, Optional, Sequence, Union",
        "",
        "from ._base import Namespace, Page",
        "",
    ]
    for tag, (ns, cls) in TAGS.items():
        if ns not in by_ns:  # AuthAPI is generated for completeness; Client signs in by itself
            continue
        lines += ["", f"class {cls}(Namespace):", f'    """{tag} operations."""', ""]
        for op_id, op in by_ns[ns]:
            name = snake(op_id)
            pargs = [snake(p) for p in op["path_params"]]
            sig = ["self"] + [f"{a}: str" for a in pargs]
            if op["body"]:
                sig.append("body: Mapping[str, Any]" if op["body"]["required"] else "body: Optional[Mapping[str, Any]] = None")
            qnames = [q for q in op["query"]]
            kw = []
            for qn in qnames:
                q = op["query"][qn]
                if q["required"]:
                    kw.append(f"{qn}: {qtype(q)}")
            for qn in qnames:
                q = op["query"][qn]
                if not q["required"]:
                    kw.append(f"{qn}: Optional[{qtype(q)}] = None")
            if kw:
                sig.append("*")
                sig += kw
            pmap = "{" + ", ".join(f"{p!r}: {snake(p)}" for p in op["path_params"]) + "}"
            qmap = "{" + ", ".join(f"{qn!r}: {qn}" for qn in qnames) + "}"
            ret = "Page" if op["paged"] else "Any"
            doc = f'{op["summary"]}. `{op["method"]} {op["path"]}` ({op["role"]}).'
            body_arg = "body" if op["body"] else "None"
            call = "_page" if op["paged"] else "_call"
            lines.append(f"    def {name}({', '.join(sig)}) -> {ret}:")
            lines.append(f'        """{doc}"""')
            lines.append(f"        return self._c.{call}({op_id!r}, path={pmap}, query={qmap}, body={body_arg})")
            lines.append("")
            if op["paged"]:
                it_name = "iter_" + name[len("list_"):] if name.startswith("list_") else "iter_" + name
                isig = ["self"] + [f"{a}: str" for a in pargs]
                ikw = [k for k in kw if not k.startswith(("cursor", "limit"))]
                if ikw:
                    isig += ["*"] + ikw
                iq = "{" + ", ".join(f"{qn!r}: {qn}" for qn in qnames if qn not in ("cursor", "limit")) + "}"
                lines.append(f"    def {it_name}({', '.join(isig)}) -> Iterator[Any]:")
                lines.append(f'        """Every item of `{name}`, following cursors 100 at a time."""')
                lines.append(f"        return self._c._iter({op_id!r}, path={pmap}, query={iq})")
                lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    sys.exit(main(pathlib.Path(args[0]), check="--check" in sys.argv))

"""Operation registry, request checks and response projection, driven by the bundled spec data."""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, List, Mapping, Optional

from .errors import InvalidRequestError

from importlib.resources import files as _files

MAX_LOCATION_IDS = 50  # longer query strings are refused before they reach the API
MAX_NUMBERS = 25

_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$"
)
_RFC3339_PARTS = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?([Zz]|[+-]\d{2}:\d{2})$"
)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NUMBER_OK = re.compile(r"^[A-Za-z0-9@#]+$")
_NUMBER_STRIP = re.compile(r"[\s+\-().]")


@lru_cache(maxsize=None)
def spec() -> Dict[str, Any]:
    text = _files("intelligence_cloud").joinpath("data/spec.json").read_text(encoding="utf-8")
    return json.loads(text)


def operation(op_id: str) -> Dict[str, Any]:
    try:
        return spec()["operations"][op_id]
    except KeyError:  # pragma: no cover - programming error
        raise KeyError(f"unknown operation {op_id}") from None


# ------------------------------------------------------------------ schema helpers

def _resolve(schema: Any) -> Any:
    seen = 0
    while isinstance(schema, dict) and "$ref" in schema:
        schema = spec()["schemas"][schema["$ref"].split("/")[-1]]
        seen += 1
        if seen > 50:  # pragma: no cover
            break
    return schema


def _object_props(schema: Any) -> Optional[Dict[str, Any]]:
    """Known properties of an object schema (merging allOf/oneOf/anyOf), or None when anything goes."""
    schema = _resolve(schema)
    if not isinstance(schema, dict):
        return None
    if schema.get("additionalProperties") is True:
        return None
    props: Dict[str, Any] = {}
    found = False
    if "properties" in schema:
        props.update(schema["properties"])
        found = True
    for key in ("allOf", "oneOf", "anyOf"):
        for part in schema.get(key, []) or []:
            sub = _object_props(part)
            if sub is None:
                return None
            found = True
            for k, v in sub.items():
                props.setdefault(k, v)
    return props if found else None


def _items_schema(schema: Any) -> Any:
    schema = _resolve(schema)
    if isinstance(schema, dict) and "items" in schema:
        return schema["items"]
    return None


def project(value: Any, schema: Any) -> Any:
    """Drop every field the published schema does not list. Unknown shapes pass through."""
    if schema is None or value is None:
        return value
    if isinstance(value, dict):
        props = _object_props(schema)
        if props is None:
            return value
        return {k: project(v, props[k]) for k, v in value.items() if k in props}
    if isinstance(value, list):
        items = _items_schema(schema)
        if items is None:
            return value
        return [project(v, items) for v in value]
    return value


def response_schema(op_id: str, status: int) -> Any:
    responses = operation(op_id)["responses"]
    if str(status) in responses:
        return responses[str(status)]
    for key in sorted(responses):
        if key.startswith("2") and responses[key] is not None:
            return responses[key]
    return None


# Inside the call detail's vcon object only the recording link and its expiry are ever passed on,
# whatever the schema lists.
RECORDING_FIELDS = ("recording_url", "recording_url_expires_at")


# Never passed on, even with keep_unknown_fields: one-time links and secret references (any "*_ref" field).
DENIED_FIELDS = frozenset({"invitation_link"})
# Always projected to the published schema, whatever the client option says: the signed-in user,
# sign-in, and every conversation-data read (calls, transcripts, alerts, tasks, insights).
ALWAYS_PROJECTED = frozenset({"getMe", "login", "refresh"})
ALWAYS_PROJECTED_NAMESPACES = frozenset({"calls", "alerts", "tasks", "insights"})


def drop_denied(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: drop_denied(v) for k, v in value.items()
                if k not in DENIED_FIELDS and not str(k).endswith("_ref")}
    if isinstance(value, list):
        return [drop_denied(v) for v in value]
    return value


def project_response(op_id: str, status: int, body: Any, keep_unknown: bool = False) -> Any:
    schema = response_schema(op_id, status)
    if (keep_unknown and op_id not in ALWAYS_PROJECTED
            and operation(op_id).get("namespace") not in ALWAYS_PROJECTED_NAMESPACES):
        out = drop_denied(body)
    else:
        out = body if schema is None else drop_denied(project(body, schema))
    if op_id == "getCall" and isinstance(out, dict) and isinstance(out.get("data"), dict):
        vcon = out["data"].get("vcon")
        if isinstance(vcon, dict):
            out["data"]["vcon"] = {k: vcon[k] for k in RECORDING_FIELDS if k in vcon}
    return out


def recording_link(body: Any) -> Optional[Dict[str, Any]]:
    """The recording link and expiry from a raw call-detail body, or None."""
    data = body.get("data") if isinstance(body, dict) else None
    vcon = data.get("vcon") if isinstance(data, dict) else None
    if not isinstance(vcon, dict) or not vcon.get("recording_url"):
        return None
    return {k: vcon.get(k) for k in RECORDING_FIELDS}


def webhook_schema(name: str) -> Any:
    return spec()["webhooks"][name]


def schema_by_name(name: str) -> Any:
    return spec()["schemas"][name]


# ------------------------------------------------------------------ request checks

def check_body(op_id: str, body: Mapping[str, Any]) -> None:
    op = operation(op_id)
    if op["body"] is None:
        raise InvalidRequestError(f"{op_id} takes no body")
    if not isinstance(body, Mapping):
        raise InvalidRequestError(f"{op_id}: body must be a mapping")
    schema = _resolve(op["body"]["schema"])
    props = _object_props(schema)
    if props is None:
        return
    unknown = sorted(set(body) - set(props))
    if unknown:
        raise InvalidRequestError(
            f"{op_id}: unknown field(s) {unknown}. Allowed: {sorted(props)}"
        )
    missing = [k for k in schema.get("required", []) if k not in body]
    if missing:
        raise InvalidRequestError(f"{op_id}: missing required field(s) {missing}")


def is_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return len(value) == 36


def format_datetime(value: Any, name: str) -> str:
    """Full RFC 3339 in UTC. Naive datetimes and date-only values are refused."""
    if isinstance(value, datetime):
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise InvalidRequestError(
                f"{name}: a datetime without a time zone is refused. Pass an aware datetime, "
                "e.g. datetime.now(timezone.utc)"
            )
        value = value.astimezone(timezone.utc)
        frac = f".{value.microsecond:06d}" if value.microsecond else ""
        return value.strftime("%Y-%m-%dT%H:%M:%S") + frac + "Z"
    if isinstance(value, date):
        raise InvalidRequestError(
            f"{name}: a date alone is refused. Pass a datetime, e.g. 2026-11-01T00:00:00Z"
        )
    if isinstance(value, str):
        v = value.strip()
        if _DATE.match(v):
            raise InvalidRequestError(
                f"{name}: {v!r} is a date only. Use a full timestamp, e.g. {v}T00:00:00Z"
            )
        if not _RFC3339.match(v):
            raise InvalidRequestError(
                f"{name}: {v!r} is not a full RFC 3339 timestamp (e.g. 2026-11-01T00:00:00Z)"
            )
        m = _RFC3339_PARTS.match(v)
        frac = (m.group(7) or "")[:6].ljust(6, "0") if m.group(7) else "0"
        off = m.group(8)
        if off in ("Z", "z"):
            tz = timezone.utc
        else:
            sign = 1 if off[0] == "+" else -1
            tz = timezone(sign * timedelta(hours=int(off[1:3]), minutes=int(off[4:6])))
        parsed = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)),
                          int(m.group(5)), int(m.group(6)), int(frac), tzinfo=tz)
        return format_datetime(parsed, name)
    raise InvalidRequestError(f"{name}: expected a datetime or RFC 3339 string")


def format_date(value: Any, name: str) -> str:
    if isinstance(value, datetime):
        raise InvalidRequestError(f"{name}: pass a date (YYYY-MM-DD), not a datetime")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and _DATE.match(value.strip()):
        return value.strip()
    raise InvalidRequestError(f"{name}: expected YYYY-MM-DD")


def clean_number(entry: str, name: str = "numbers") -> str:
    """Strip formatting. A North American number written with its leading 1 (11 digits) is sent as its
    last 10 digits, so it also matches records stored without the 1."""
    v = _NUMBER_STRIP.sub("", str(entry))
    if not _NUMBER_OK.match(v):
        raise InvalidRequestError(f"{name}: {entry!r} must be digits (letters, @ and # are also allowed)")
    if len(v) == 11 and v.isdigit() and v.startswith("1"):
        v = v[1:]
    return v


def _as_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [p.strip() for p in value.split(",") if p.strip()]
    return [str(v).strip() for v in value]


def encode_query(op_id: str, query: Mapping[str, Any]) -> Dict[str, str]:
    op = operation(op_id)
    allowed = op["query"]
    out: Dict[str, str] = {}
    for name, value in query.items():
        if name not in allowed:
            raise InvalidRequestError(f"{op_id}: unknown filter {name!r}. Allowed: {sorted(allowed)}")
        q = allowed[name]
        if value is None:
            if q.get("required"):
                raise InvalidRequestError(f"{op_id}: {name} is required")
            continue
        out[name] = _encode_one(op_id, name, q, value)
    for name, q in allowed.items():
        if q.get("required") and name not in out:
            raise InvalidRequestError(f"{op_id}: {name} is required")
    return out


def _encode_one(op_id: str, name: str, q: Mapping[str, Any], value: Any) -> str:
    typ = q.get("type")
    fmt = q.get("format")
    if q.get("enum") == ["true"]:
        if value is True:
            return "true"
        raise InvalidRequestError(f"{name}: only True is supported (leave it out otherwise)")
    if typ == "boolean":
        if not isinstance(value, bool):
            raise InvalidRequestError(f"{name}: expected True or False")
        return "true" if value else "false"
    if typ == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidRequestError(f"{name}: expected an integer")
        if "minimum" in q and value < q["minimum"]:
            raise InvalidRequestError(f"{name}: must be >= {q['minimum']}")
        if "maximum" in q and value > q["maximum"]:
            raise InvalidRequestError(f"{name}: must be <= {q['maximum']}")
        return str(value)
    if typ == "array":
        items = _as_list(value)
        item_fmt = (q.get("items") or {}).get("format")
        if name == "numbers":
            items = [clean_number(i) for i in items]
            limit = min(q.get("maxItems", MAX_NUMBERS), MAX_NUMBERS)
        else:
            limit = q.get("maxItems", 100)
        if name == "location_id":
            limit = MAX_LOCATION_IDS
        deduped: List[str] = []
        for i in items:
            if i not in deduped:
                deduped.append(i)
        if not deduped:
            raise InvalidRequestError(f"{name}: empty list")
        if len(deduped) > limit:
            raise InvalidRequestError(f"{name}: at most {limit} entries per request (got {len(deduped)})")
        if item_fmt == "uuid":
            bad = [i for i in deduped if not is_uuid(i)]
            if bad:
                raise InvalidRequestError(f"{name}: not a UUID: {bad[0]!r}")
        return ",".join(deduped)
    # strings
    if fmt == "date-time":
        return format_datetime(value, name)
    if fmt == "date":
        return format_date(value, name)
    if not isinstance(value, str):
        raise InvalidRequestError(f"{name}: expected a string")
    if "enum" in q and value not in q["enum"]:
        raise InvalidRequestError(f"{name}: {value!r} is not one of {q['enum']}")
    if fmt == "uuid" and not is_uuid(value):
        raise InvalidRequestError(f"{name}: not a UUID: {value!r}")
    return value

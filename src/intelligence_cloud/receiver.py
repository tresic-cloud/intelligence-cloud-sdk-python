"""Receive the After Call webhook: parse the event and drop duplicates.

The webhook sends every call at the location, unsigned. Use an unguessable HTTPS URL, answer 2xx
within 2 seconds and do the work afterwards. Treat an event as a notification: read the call with
``client.intelligence.get_call(event.call.id)`` before you write it anywhere. Expect repeats of the
same ``call.id``; upsert on it. Event types you don't handle come back as :class:`UnknownEvent`:
answer 2xx and ignore them.
"""
from __future__ import annotations

import json
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Protocol, Union

from . import _spec
from .errors import PayloadTooLargeError, WebhookPayloadError

AFTER_CALL_EVENT_TYPE = "end_of_call_summary"
MAX_EVENT_BYTES = 262_144  # 256 KB; answer 413 to anything larger


@dataclass
class AfterCallCall:
    id: str
    call_type: str
    duration_seconds: int
    call_date: date
    caller_name: Optional[str] = None
    caller_number: Optional[str] = None
    callee_name: Optional[str] = None
    callee_number: Optional[str] = None
    platform: Optional[str] = None


@dataclass
class AfterCallSummary:
    text: Optional[str] = None
    sentiment: Optional[str] = None
    key_points: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)


@dataclass
class AfterCallLocation:
    id: str
    company_id: Optional[str] = None
    connector_id: Optional[str] = None


@dataclass
class AfterCallEvent:
    """An ``end_of_call_summary`` event. Fetch full detail with ``client.intelligence.get_call(event.call.id)``."""

    version: str
    type: str
    is_test: bool
    location_id: str
    timestamp: datetime
    call: AfterCallCall
    location: AfterCallLocation
    summary: Optional[AfterCallSummary] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class UnknownEvent:
    """A delivery whose ``type`` this SDK version does not handle. Answer 2xx and ignore it."""

    type: Optional[str]
    version: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


def _req(d: Mapping[str, Any], key: str, typ: Any, where: str) -> Any:
    if key not in d:
        raise WebhookPayloadError(f"{where}.{key} is missing")
    v = d[key]
    if typ is int and isinstance(v, bool):
        raise WebhookPayloadError(f"{where}.{key} has the wrong type")
    if not isinstance(v, typ):
        raise WebhookPayloadError(f"{where}.{key} has the wrong type")
    return v


def _ts(value: str, where: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, AttributeError):
        try:
            return datetime.fromisoformat(_spec.format_datetime(value, where).replace("Z", "+00:00"))
        except Exception:
            raise WebhookPayloadError(f"{where} is not an RFC 3339 timestamp") from None


def parse_after_call_event(body: Union[bytes, str, Mapping[str, Any]],
                           max_bytes: int = MAX_EVENT_BYTES) -> Union[AfterCallEvent, UnknownEvent]:
    """Parse and check an After Call webhook body. Fields outside the published schema are dropped.

    Returns :class:`AfterCallEvent`, or :class:`UnknownEvent` for any other event type (answer 2xx and
    ignore it). Raises :class:`PayloadTooLargeError` (answer 413) for a body over ``max_bytes`` and
    :class:`WebhookPayloadError` (answer 400) for a body that is not JSON or a malformed After Call event.
    """
    if isinstance(body, str):
        body = body.encode("utf-8")
    if isinstance(body, (bytes, bytearray)):
        if max_bytes and len(body) > max_bytes:
            raise PayloadTooLargeError(f"body is larger than {max_bytes} bytes")
        try:
            body = json.loads(bytes(body).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise WebhookPayloadError("body is not JSON") from None
    if not isinstance(body, Mapping):
        raise WebhookPayloadError("body is not a JSON object")
    if body.get("type") != AFTER_CALL_EVENT_TYPE:
        typ, ver = body.get("type"), body.get("version")
        return UnknownEvent(type=typ if isinstance(typ, str) else None,
                            version=ver if isinstance(ver, str) else None, raw=dict(body))
    data = _spec.project(dict(body), _spec.schema_by_name("AfterCallSummaryEvent"))
    call = _req(data, "call", dict, "event")
    loc = _req(data, "location", dict, "event")
    try:
        call_date = date.fromisoformat(_req(call, "call_date", str, "call"))
    except ValueError:
        raise WebhookPayloadError("call.call_date is not YYYY-MM-DD") from None
    summary = data.get("summary")
    return AfterCallEvent(
        version=_req(data, "version", str, "event"),
        type=data["type"],
        is_test=_req(data, "is_test", bool, "event"),
        location_id=_req(data, "location_id", str, "event"),
        timestamp=_ts(_req(data, "timestamp", str, "event"), "timestamp"),
        call=AfterCallCall(
            id=_req(call, "id", str, "call"),
            call_type=_req(call, "call_type", str, "call"),
            duration_seconds=_req(call, "duration_seconds", int, "call"),
            call_date=call_date,
            caller_name=call.get("caller_name"),
            caller_number=call.get("caller_number"),
            callee_name=call.get("callee_name"),
            callee_number=call.get("callee_number"),
            platform=call.get("platform"),
        ),
        location=AfterCallLocation(id=loc.get("id") or data["location_id"], company_id=loc.get("company_id"),
                                   connector_id=loc.get("connector_id")),
        summary=AfterCallSummary(
            text=summary.get("text"), sentiment=summary.get("sentiment"),
            key_points=list(summary.get("key_points") or []), action_items=list(summary.get("action_items") or []),
        ) if isinstance(summary, dict) else None,
        raw=data,
    )


class DedupStore(Protocol):
    """Remembers which keys were seen. ``add`` returns True when the key is new."""

    def add(self, key: str) -> bool: ...


class MemoryDedupStore:
    """In-memory LRU of the most recent keys (process-local)."""

    def __init__(self, max_size: int = 10_000):
        self.max_size = max_size
        self._keys: "OrderedDict[str, None]" = OrderedDict()
        self._lock = threading.Lock()

    def add(self, key: str) -> bool:
        with self._lock:
            if key in self._keys:
                self._keys.move_to_end(key)
                return False
            self._keys[key] = None
            if len(self._keys) > self.max_size:
                self._keys.popitem(last=False)
            return True


class Deduplicator:
    """Spots repeat deliveries of the same call. Pass a shared ``store`` when you run several workers.

    The same name and meaning in every SDK: ``is_duplicate`` (Python), ``isDuplicate`` (PHP,
    TypeScript) returns True for a repeat. A repeat can carry newer data: when you keep a copy, upsert
    on ``call.id`` rather than dropping the later delivery.
    """

    def __init__(self, max_size: int = 10_000, store: Optional[DedupStore] = None):
        self.store = store or MemoryDedupStore(max_size)

    def is_duplicate(self, event_or_call_id: Union[AfterCallEvent, str]) -> bool:
        """True if this call was seen before; otherwise records it and returns False."""
        key = event_or_call_id.call.id if isinstance(event_or_call_id, AfterCallEvent) else str(event_or_call_id)
        if not key:
            raise ValueError("a call id is required")
        return not self.store.add(key)

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:  # pragma: no cover
    from .client import Client


class Namespace:
    """A group of operations sharing the client's session."""

    def __init__(self, client: "Client"):
        self._c = client


def unwrap(body: Any) -> Any:
    """Return the record inside a response: ``data.attributes`` when present, else ``data``."""
    if isinstance(body, dict) and "data" in body:
        data = body["data"]
        if isinstance(data, dict) and "attributes" in data and isinstance(data["attributes"], dict):
            return data["attributes"]
        return data
    return body


def _flatten(item: Any) -> Any:
    if isinstance(item, dict) and "attributes" in item and isinstance(item["attributes"], dict):
        return item["attributes"]
    return item


@dataclass
class Page:
    """One page of a list.

    ``items`` are the records (resource ``attributes`` already unwrapped). ``raw`` is the whole response,
    including summaries such as ``data.summary`` on calls and alerts.
    """

    items: List[Any]
    next_cursor: Optional[str]
    has_more: bool
    total: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    @classmethod
    def from_body(cls, body: Any) -> "Page":
        body = body if isinstance(body, dict) else {}
        data = body.get("data")
        items: List[Any] = []
        total = None
        if isinstance(data, list):
            items = [_flatten(i) for i in data]
        elif isinstance(data, dict):
            for key in ("calls", "alerts"):
                if isinstance(data.get(key), list):
                    items = [_flatten(i) for i in data[key]]
                    break
            summary = data.get("summary") or {}
            total = summary.get("total", summary.get("total_calls"))
        paging = body.get("pagination") or body.get("meta") or body
        cursor = paging.get("next_cursor") if isinstance(paging, dict) else None
        has_more = bool(paging.get("has_more")) if isinstance(paging, dict) else False
        if isinstance(paging, dict):
            total = paging.get("total_count", paging.get("total", total))
        if not has_more:
            cursor = None
        return cls(items=items, next_cursor=cursor or None, has_more=has_more and bool(cursor), total=total, raw=body)

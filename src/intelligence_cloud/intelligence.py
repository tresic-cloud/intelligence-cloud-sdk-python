"""Conversation intelligence: calls, alerts, tasks, insights and webhook configuration."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional, Sequence, Union

from . import _spec
from ._base import Namespace, Page, unwrap
from .errors import FrontlineRequiredError, InvalidRequestError

if TYPE_CHECKING:  # pragma: no cover
    from .client import Client

When = Union[str, datetime]
Ids = Union[str, Sequence[str]]


@dataclass
class RecordingLink:
    """A signed link to the call's audio (WAV). No Authorization header is needed and Range requests
    work. It expires 120 minutes after issue. Anyone holding it can download the audio: never log it."""

    url: str = field(repr=False)
    expires_at: Optional[datetime]


@dataclass
class WebhookTestResult:
    """The outcome of a test send: whether the receiver answered 2xx, and its HTTP status."""

    success: bool
    http_status: Optional[int]


def _search_term(phone: Optional[str], text: Optional[str]) -> Optional[str]:
    if phone is not None and text is not None:
        raise InvalidRequestError("Pass phone or text, not both: the API has one search field")
    term = phone if phone is not None else text
    if term is None:
        return None
    term = str(term).strip()
    if len(term) < 2:
        raise InvalidRequestError("search terms need at least 2 characters (shorter ones are ignored by the API)")
    return term


class Intelligence(Namespace):
    """Read conversation data with a **frontline** login, and configure webhooks with an admin login."""

    def __init__(self, client: "Client"):
        super().__init__(client)
        self._me: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------ account

    def whoami(self) -> Dict[str, Any]:
        """The signed-in user (``GET /me``): role, company, locations, products."""
        self._me = unwrap(self._c.account.get_me()) or {}
        return self._me

    def require_frontline(self) -> Dict[str, Any]:
        """Raise FrontlineRequiredError unless this is a frontline login (admins see empty lists)."""
        me = self._me if self._me is not None else self.whoami()
        if me.get("role") != "frontline_user":
            raise FrontlineRequiredError(me.get("role"))
        return me

    # ------------------------------------------------------------------ calls

    def _call_filters(self, phone, text, date_from, date_to, status, sentiment, has_open_tasks, multi_leg,
                      location_ids, company_id) -> Dict[str, Any]:
        self.require_frontline()
        return dict(search=_search_term(phone, text), date_from=date_from, date_to=date_to, status=status,
                    sentiment=sentiment, has_open_tasks=has_open_tasks, multi_leg=multi_leg,
                    location_id=location_ids, company_id=company_id)

    def search_calls(self, phone: Optional[str] = None, text: Optional[str] = None,
                     date_from: Optional[When] = None, date_to: Optional[When] = None,
                     status: Optional[str] = None, sentiment: Optional[str] = None,
                     has_open_tasks: Optional[bool] = None, multi_leg: Optional[bool] = None,
                     location_ids: Optional[Ids] = None, *, company_id: Optional[str] = None,
                     limit: Optional[int] = None, cursor: Optional[str] = None) -> Page:
        """One page of calls, newest first. ``phone`` and ``text`` both search (one or the other).

        Without ``date_from`` the window starts at 00:00 UTC seven days ago.
        """
        f = self._call_filters(phone, text, date_from, date_to, status, sentiment, has_open_tasks, multi_leg,
                               location_ids, company_id)
        return self._c.calls.list_calls(limit=limit, cursor=cursor, **f)

    def iter_calls(self, phone: Optional[str] = None, text: Optional[str] = None,
                   date_from: Optional[When] = None, date_to: Optional[When] = None,
                   status: Optional[str] = None, sentiment: Optional[str] = None,
                   has_open_tasks: Optional[bool] = None, multi_leg: Optional[bool] = None,
                   location_ids: Optional[Ids] = None, *, company_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        """Every matching call, following cursors 100 at a time."""
        f = self._call_filters(phone, text, date_from, date_to, status, sentiment, has_open_tasks, multi_leg,
                               location_ids, company_id)
        return self._c.calls.iter_calls(**f)

    def get_call(self, call_id: str) -> Dict[str, Any]:
        """Call detail: summary, analysis, sentiment, tasks."""
        self.require_frontline()
        return unwrap(self._c.calls.get_call(call_id))

    def get_transcript(self, call_id: str) -> List[Dict[str, Any]]:
        """Transcript segments: ``time``, ``speaker`` ("Speaker 1"...), ``name``, ``text``."""
        self.require_frontline()
        data = unwrap(self._c.calls.get_call_transcript(call_id)) or {}
        return data.get("transcript") or []

    def get_recording_url(self, call_id: str) -> Optional[RecordingLink]:
        """The call's recording link and its expiry, or None when the call has no recording.

        Only the link and expiry are returned. Fetch a new link when it expires."""
        self.require_frontline()
        resp = self._c._request("getCall", {"callId": call_id}, {}, None)
        link = _spec.recording_link(self._c._json(resp))
        if link is None:
            return None
        expires = link.get("recording_url_expires_at")
        try:
            when = datetime.fromisoformat(_spec.format_datetime(expires, "expires_at").replace("Z", "+00:00")) \
                if expires else None
        except (ValueError, InvalidRequestError):
            when = None
        return RecordingLink(url=link["recording_url"], expires_at=when)

    # ------------------------------------------------------------------ alerts

    def _alert_filters(self, alert_name, numbers, text, sentiment, date_from, date_to, location_ids, topic,
                       company_id) -> Dict[str, Any]:
        self.require_frontline()
        if numbers is not None and isinstance(numbers, str):
            numbers = [numbers]
        return dict(keyword=alert_name, numbers=numbers, search=_search_term(None, text), sentiment=sentiment,
                    date_from=date_from, date_to=date_to, location_id=location_ids, topic=topic,
                    company_id=company_id)

    def search_alerts(self, alert_name: Optional[str] = None, numbers: Optional[Sequence[str]] = None,
                      text: Optional[str] = None, sentiment: Optional[str] = None,
                      date_from: Optional[When] = None, date_to: Optional[When] = None,
                      location_ids: Optional[Ids] = None, *, topic: Optional[str] = None,
                      company_id: Optional[str] = None, limit: Optional[int] = None,
                      cursor: Optional[str] = None) -> Page:
        """One page of First Alert hits, newest first.

        ``alert_name`` is the exact, case-sensitive rule name. ``numbers`` (up to 25) match caller or
        callee by substring; formatting is stripped for you.
        """
        f = self._alert_filters(alert_name, numbers, text, sentiment, date_from, date_to, location_ids, topic,
                                company_id)
        return self._c.alerts.list_alerts(limit=limit, cursor=cursor, **f)

    def iter_alerts(self, alert_name: Optional[str] = None, numbers: Optional[Sequence[str]] = None,
                    text: Optional[str] = None, sentiment: Optional[str] = None,
                    date_from: Optional[When] = None, date_to: Optional[When] = None,
                    location_ids: Optional[Ids] = None, *, topic: Optional[str] = None,
                    company_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        f = self._alert_filters(alert_name, numbers, text, sentiment, date_from, date_to, location_ids, topic,
                                company_id)
        return self._c.alerts.iter_alerts(**f)

    def get_alert(self, alert_id: str, with_call: bool = False) -> Optional[Dict[str, Any]]:
        """One alert by id (searched by id, no date window). With ``with_call`` the call detail is
        added under ``call``. Returns None when the alert is not visible."""
        self.require_frontline()
        aid = alert_id.strip().lower()
        page = self._c.alerts.list_alerts(search=aid, limit=10)
        alert = next((a for a in page.items if a.get("id") == aid), None)
        if alert is not None and with_call and alert.get("call_id"):
            alert = dict(alert)
            alert["call"] = self.get_call(alert["call_id"])
        return alert

    def get_alerts_dashboard(self, date_from: Optional[When] = None, date_to: Optional[When] = None,
                             location_ids: Optional[Ids] = None, *,
                             company_id: Optional[str] = None) -> Dict[str, Any]:
        self.require_frontline()
        return unwrap(self._c.alerts.get_alerts_dashboard(date_from=date_from, date_to=date_to,
                                                          location_id=location_ids, company_id=company_id))

    # ------------------------------------------------------------------ tasks

    def _task_filters(self, kw: Dict[str, Any]) -> Dict[str, Any]:
        self.require_frontline()
        kw["location_id"] = kw.pop("location_ids")
        return kw

    def list_tasks(self, status: Optional[str] = None, call_id: Optional[str] = None,
                   task_id: Optional[str] = None, due_on: Optional[Union[str, date]] = None,
                   date_from: Optional[When] = None, date_to: Optional[When] = None,
                   search: Optional[str] = None, location_ids: Optional[Ids] = None, *,
                   today_start: Optional[When] = None, company_id: Optional[str] = None,
                   limit: Optional[int] = None, cursor: Optional[str] = None) -> Page:
        """One page of follow-up tasks. ``date_from``/``date_to`` filter on creation time; no default window."""
        f = self._task_filters(dict(status=status, call_id=call_id, task_id=task_id, due_on=due_on,
                                    date_from=date_from, date_to=date_to, search=_search_term(None, search),
                                    location_ids=location_ids, today_start=today_start, company_id=company_id))
        return self._c.tasks.list_tasks(limit=limit, cursor=cursor, **f)

    def iter_tasks(self, status: Optional[str] = None, call_id: Optional[str] = None,
                   task_id: Optional[str] = None, due_on: Optional[Union[str, date]] = None,
                   date_from: Optional[When] = None, date_to: Optional[When] = None,
                   search: Optional[str] = None, location_ids: Optional[Ids] = None, *,
                   today_start: Optional[When] = None,
                   company_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        f = self._task_filters(dict(status=status, call_id=call_id, task_id=task_id, due_on=due_on,
                                    date_from=date_from, date_to=date_to, search=_search_term(None, search),
                                    location_ids=location_ids, today_start=today_start, company_id=company_id))
        return self._c.tasks.iter_tasks(**f)

    # ------------------------------------------------------------------ insights

    def get_insights_dashboard(self, start: When, end: When, trending_limit: Optional[int] = None,
                               location_ids: Optional[Ids] = None, *,
                               company_id: Optional[str] = None) -> Dict[str, Any]:
        """Insights Hub dashboard for a window (both ends required, at most 366 days)."""
        self.require_frontline()
        if trending_limit is not None and not 1 <= trending_limit <= 10:
            raise InvalidRequestError("trending_limit: 1 to 10")
        return unwrap(self._c.insights.get_insights_dashboard(start=start, end=end, trending_limit=trending_limit,
                                                              location_id=location_ids, company_id=company_id))

    def list_topic_calls(self, slug: str, date_from: Optional[When] = None, date_to: Optional[When] = None,
                         sentiment: Optional[str] = None, outcome: Optional[str] = None,
                         search: Optional[str] = None, location_ids: Optional[Ids] = None, *,
                         company_id: Optional[str] = None, limit: Optional[int] = None,
                         cursor: Optional[str] = None) -> Page:
        """Calls for one topic (slug from the dashboard's ``topic_call_volumes``)."""
        self.require_frontline()
        return self._c.insights.list_topic_calls(slug, date_from=date_from, date_to=date_to, sentiment=sentiment,
                                                 outcome=outcome, search=_search_term(None, search),
                                                 location_id=location_ids, company_id=company_id, limit=limit,
                                                 cursor=cursor)

    def iter_topic_calls(self, slug: str, date_from: Optional[When] = None, date_to: Optional[When] = None,
                         sentiment: Optional[str] = None, outcome: Optional[str] = None,
                         search: Optional[str] = None, location_ids: Optional[Ids] = None, *,
                         company_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        self.require_frontline()
        return self._c.insights.iter_topic_calls(slug, date_from=date_from, date_to=date_to, sentiment=sentiment,
                                                 outcome=outcome, search=_search_term(None, search),
                                                 location_id=location_ids, company_id=company_id)

    # ------------------------------------------------------------------ webhook configuration (admin)

    def get_after_call_webhook(self, location_id: str) -> Optional[Dict[str, Any]]:
        """The location's After Call webhook (``webhook_url``, ``enabled``), or None when not set."""
        return unwrap(self._c.webhooks.get_after_call_webhook(location_id))

    def set_after_call_webhook(self, location_id: str, url: str, enabled: bool = True) -> Dict[str, Any]:
        """Set the After Call webhook (HTTPS). It receives every call at the location. Pause with
        ``enabled=False``; there is no delete."""
        _https(url)
        return unwrap(self._c.webhooks.save_after_call_webhook(location_id, {"webhook_url": url, "enabled": enabled}))

    def test_after_call_webhook(self, location_id: str) -> WebhookTestResult:
        """Send the test payload to the saved URL."""
        data = unwrap(self._c.webhooks.test_after_call_webhook(location_id)) or {}
        return WebhookTestResult(bool(data.get("success")), data.get("http_status"))

    def get_first_alert_webhook(self, location_id: str) -> Optional[str]:
        """The First Alert location webhook URL, or None."""
        return (unwrap(self._c.first_alert.get_first_alert_config(location_id)) or {}).get("webhook_url")

    def set_first_alert_webhook(self, location_id: str, url: Optional[str]) -> Dict[str, Any]:
        """Set (or clear with None) the First Alert location webhook. Monitored numbers are kept."""
        if url is not None:
            _https(url)
        fa = self._c.first_alert
        cfg = unwrap(fa.get_first_alert_config(location_id)) or {}
        from .resources import merge_mappings
        mappings: List[Dict[str, Any]] = []
        for m in cfg.get("connector_mappings") or []:
            mappings = merge_mappings(mappings, m["connector_id"], add=m.get("monitored_numbers") or [])
        return unwrap(fa.save_first_alert_config(location_id, {"webhook_url": url, "connector_mappings": mappings}))

    def test_first_alert_webhook(self, location_id: str, url: Optional[str] = None) -> WebhookTestResult:
        """Send a test to ``url`` (default: the saved URL)."""
        target = url or self.get_first_alert_webhook(location_id)
        if not target:
            raise InvalidRequestError("No First Alert webhook URL is set for this location")
        _https(target)
        data = unwrap(self._c.first_alert.test_first_alert_webhook(location_id, {"url": target})) or {}
        return WebhookTestResult(bool(data.get("success")), data.get("status_code"))


def _https(url: str) -> None:
    if not isinstance(url, str) or not url.lower().startswith("https://"):
        raise InvalidRequestError("Webhook URLs must use HTTPS")

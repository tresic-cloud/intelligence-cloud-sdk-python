"""The Intelligence Cloud API client."""
from __future__ import annotations

import contextlib
import json
import random
import threading
import time
import uuid
from typing import Any, Callable, ContextManager, Dict, Iterator, Mapping, Optional
from urllib.parse import quote, urlsplit

import httpx

from . import _spec
from ._base import Page
from ._version import __version__
from .auth import MemoryTokenStore, Tokens, TokenStore
from .errors import (
    EXTENSION_CONFLICT_MESSAGE,
    ApiError,
    AuthError,
    ConflictError,
    InvalidRequestError,
    MfaRequiredError,
    NotFoundError,
    PasswordExpiredError,
    RateLimitError,
    ValidationError,
    extension_conflict_numbers,
    requested_numbers,
)

DEFAULT_BASE_URL = "https://app.intelligence.cloud/api/v1"

# Test endpoints whose error text is never surfaced (only success and the HTTP status).
SANITIZED_ERRORS = {"testConnector", "testFirstAlertWebhook", "testAfterCallWebhook"}
# Endpoints whose 409 is the extension-conflict check. The SDK replaces its text with a fixed message.
EXTENSION_CONFLICT_OPS = {"setUserNumberMappings", "updateUserAfterCallSettings"}
RETRY_METHODS = {"GET", "PUT", "PATCH", "DELETE"}
LOGIN_RATE_LIMIT_WAIT = 60.0
MAX_RETRY_AFTER = 60.0  # a longer Retry-After is not waited out: the request fails with RateLimitError
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def check_base_url(base_url: str) -> str:
    """Refuse anything but https, except on this machine (localhost, 127.0.0.1, ::1)."""
    parts = urlsplit(base_url)
    host = (parts.hostname or "").lower()
    if parts.scheme == "https" and host:
        return base_url
    if parts.scheme == "http" and host in LOCAL_HOSTS:
        return base_url
    raise InvalidRequestError("base_url must be an https:// URL (http:// only for localhost)")


class Client:
    """Signs in with an integration user's email and password and calls the API.

    One client per credential. Admin (reseller admin) and frontline logins see different data:
    use one client for each.

    >>> client = Client(email="integration@example.com", password="...")
    >>> client.intelligence.whoami()["role"]
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        email: Optional[str] = None,
        password: Optional[str] = None,
        token_store: Optional[TokenStore] = None,
        timeout: float = 30,
        *,
        user_agent: Optional[str] = None,
        max_retries: int = 3,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
        login_rate_limit_wait: float = LOGIN_RATE_LIMIT_WAIT,
        keep_unknown_fields: bool = False,
    ):
        self.base_url = check_base_url(base_url).rstrip("/")
        self._email = email
        self._password = password
        self._store: TokenStore = token_store or MemoryTokenStore()
        self._auth_lock = threading.Lock()
        self._max_retries = max_retries
        self._sleep = sleep
        self._login_wait = max(0.0, float(login_rate_limit_wait))
        self.keep_unknown_fields = keep_unknown_fields
        ua = f"intelligence-cloud-python/{__version__}"
        if user_agent:
            ua = f"{user_agent} {ua}"
        self._http = httpx.Client(timeout=timeout, transport=transport, headers={"User-Agent": ua})
        self._spent_refresh_tokens: set = set()

        from .resources import (
            AccountAPI, AfterCallSettingsAPI, AlertsAPI, CallsAPI, CompaniesAPI, ConnectorsAPI,
            FirstAlertAPI, GroupsAPI, InsightsAPI, InsightsHubAPI, LocationsAPI, ProductsAPI,
            ResellersAPI, SsoAPI, TasksAPI, UsersAPI, WebhooksAPI,
        )
        from .intelligence import Intelligence
        from .workflows import Workflows

        self.resellers = ResellersAPI(self)
        self.companies = CompaniesAPI(self)
        self.sso = SsoAPI(self)
        self.products = ProductsAPI(self)
        self.locations = LocationsAPI(self)
        self.groups = GroupsAPI(self)
        self.connectors = ConnectorsAPI(self)
        self.first_alert = FirstAlertAPI(self)
        self.insights_hub = InsightsHubAPI(self)
        self.users = UsersAPI(self)
        self.after_call_settings = AfterCallSettingsAPI(self)
        self.account = AccountAPI(self)
        self.calls = CallsAPI(self)
        self.alerts = AlertsAPI(self)
        self.tasks = TasksAPI(self)
        self.insights = InsightsAPI(self)
        self.webhooks = WebhooksAPI(self)
        self.intelligence = Intelligence(self)
        self.workflows = Workflows(self)

    def __repr__(self) -> str:
        return f"Client(base_url={self.base_url!r}, email={self._email!r})"

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close the HTTP connections. This does not sign out; tokens simply expire."""
        self._http.close()

    # ------------------------------------------------------------------ auth

    def _store_lock(self) -> ContextManager[Any]:
        """The token store's own (cross-process) lock, when it has one."""
        lock = getattr(self._store, "lock", None)
        return lock() if callable(lock) else contextlib.nullcontext()

    def login(self) -> Dict[str, Any]:
        """Sign in now and return the signed-in user. The client also signs in by itself on first use."""
        with self._auth_lock, self._store_lock():
            return self._login_locked()

    def logout(self) -> None:
        """Sign out. **This ends every session of this user**, including the web app.

        The SDK never calls it by itself. Integration jobs normally let tokens expire instead.
        """
        tokens = self._store.get()
        if tokens is None:
            return
        resp = self._send_raw("POST", "/auth/logout", op_id="logout", tokens=tokens)
        self._store.set(None)
        if resp.status_code >= 400 and resp.status_code != 401:
            self._raise(resp, "logout")

    def _login_locked(self) -> Dict[str, Any]:
        if not self._email or not self._password:
            text = "No credentials: pass email and password to Client"
            raise AuthError(401, None, text, public_message=text)
        body = {"email": self._email, "password": self._password}
        waited = False
        while True:
            resp = self._send_with_retries("POST", "/auth/login", op_id="login", json_body=body,
                                           auth=False, retry_429=False)
            if resp.status_code == 429 and not waited and self._login_wait > 0:
                waited = True
                self._sleep(self._login_wait)
                continue
            break
        if resp.status_code >= 400:
            self._raise(resp, "login")
        data = _spec.project_response("login", resp.status_code, self._json(resp))
        if not isinstance(data, dict):
            raise AuthError(resp.status_code, None, "Unexpected sign-in response",
                            public_message="Unexpected sign-in response")
        if data.get("status") == "mfa_required":
            raise MfaRequiredError()
        if data.get("password_expired"):
            text = "The password has expired. Change it in the app, then sign in again."
            raise PasswordExpiredError(resp.status_code, "password_expired", text, public_message=text)
        self._store.set(self._tokens_from(data))
        return data.get("user") or {}

    @staticmethod
    def _tokens_from(data: Mapping[str, Any]) -> Tokens:
        expires_in = data.get("expires_in") or 0
        return Tokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=(time.time() + float(expires_in)) if expires_in else 0.0,
        )

    def _current_tokens(self) -> Tokens:
        tokens = self._store.get()
        if tokens is not None and not tokens.expired():
            return tokens
        with self._auth_lock, self._store_lock():
            tokens = self._store.get()  # re-read: another thread or process may have renewed already
            if tokens is None:
                self._login_locked()
            elif tokens.expired():
                self._renew_locked(tokens)
            return self._store.get()  # type: ignore[return-value]

    def _renew(self, stale: Tokens) -> Tokens:
        with self._auth_lock, self._store_lock():
            current = self._store.get()
            if current is not None and current.access_token != stale.access_token:
                return current  # another thread or process already renewed
            self._renew_locked(current or stale)
            return self._store.get()  # type: ignore[return-value]

    def _renew_locked(self, tokens: Tokens) -> None:
        """Rotate the refresh token. A refresh token is used once.

        A 429 means the token was not used: wait and send the same token again (it never turns into a
        sign-in, which has a much lower limit). Any other failure: sign in again.
        """
        refresh_token = tokens.refresh_token
        if refresh_token in self._spent_refresh_tokens:
            self._login_locked()
            return
        attempt = 0
        while True:
            try:
                resp = self._send_with_retries("POST", "/auth/refresh", op_id="refresh",
                                               json_body={"refresh_token": refresh_token}, auth=False,
                                               retry_429=False)
            except httpx.HTTPError:
                resp = None
            if resp is None or resp.status_code != 429:
                break
            wait = self._backoff(attempt, resp.headers.get("Retry-After"))
            if attempt >= self._max_retries or wait is None:
                self._raise(resp, "refresh")
            self._sleep(wait)  # type: ignore[arg-type]
            attempt += 1
        self._spent_refresh_tokens.add(refresh_token)
        if resp is not None and resp.status_code == 200:
            data = _spec.project_response("refresh", 200, self._json(resp))
            if isinstance(data, dict) and data.get("access_token") and data.get("refresh_token"):
                self._store.set(self._tokens_from(data))  # store the new pair before using it
                return
        self._store.set(None)
        self._login_locked()

    # ------------------------------------------------------------------ transport

    @staticmethod
    def _json(resp: httpx.Response) -> Any:
        if not resp.content:
            return None
        try:
            return resp.json()
        except (ValueError, json.JSONDecodeError):
            return None

    def _url(self, path: str) -> str:
        return self.base_url + path

    def _send_raw(self, method: str, path: str, *, op_id: str, tokens: Optional[Tokens] = None,
                  params: Optional[Mapping[str, str]] = None, json_body: Any = None,
                  headers: Optional[Mapping[str, str]] = None) -> httpx.Response:
        h = {"Accept": "application/json", "X-Request-ID": str(uuid.uuid4())}
        if headers:
            h.update(headers)
        if tokens is not None:
            h["Authorization"] = f"Bearer {tokens.access_token}"
        return self._http.request(method, self._url(path), params=params or None,
                                  json=json_body, headers=h)

    def _send_with_retries(self, method: str, path: str, *, op_id: str, params=None, json_body=None,
                           headers: Optional[Dict[str, str]] = None, auth: bool = True,
                           retry_429: bool = True) -> httpx.Response:
        headers = dict(headers or {})
        idempotent = method in RETRY_METHODS or "Idempotency-Key" in headers
        attempt = 0
        refreshed = False
        while True:
            if attempt > 0 and "Idempotency-Key" in headers:
                headers["Accept-Encoding"] = "identity"
            tokens = self._current_tokens() if auth else None
            try:
                resp = self._send_raw(method, path, op_id=op_id, tokens=tokens, params=params,
                                      json_body=json_body, headers=headers)
            except (httpx.TransportError,) as exc:
                if idempotent and attempt < self._max_retries:
                    self._sleep(self._backoff(attempt, None) or 0.0)
                    attempt += 1
                    continue
                raise exc
            if resp.status_code == 401 and auth and not refreshed:
                refreshed = True
                self._renew(tokens)  # type: ignore[arg-type]
                continue
            retryable = (resp.status_code == 429 and retry_429) or (resp.status_code >= 500 and idempotent)
            if retryable and attempt < self._max_retries:
                wait = self._backoff(attempt, resp.headers.get("Retry-After"))
                if wait is None:
                    return resp  # Retry-After above MAX_RETRY_AFTER: fail now rather than block
                self._sleep(wait)
                attempt += 1
                continue
            return resp

    @staticmethod
    def _backoff(attempt: int, retry_after: Optional[str]) -> Optional[float]:
        """Seconds to wait before the next try, or None when Retry-After asks for more than
        MAX_RETRY_AFTER seconds."""
        if retry_after:
            try:
                wait = max(0.0, float(retry_after))
            except ValueError:
                wait = -1.0
            if wait > MAX_RETRY_AFTER:
                return None
            if wait >= 0:
                return wait
        base = min(8.0, 0.5 * (2 ** attempt))
        return base + random.uniform(0, base / 2)

    # ------------------------------------------------------------------ errors

    @staticmethod
    def _request_body(resp: httpx.Response) -> Any:
        try:
            content = resp.request.content
            return json.loads(content) if content else None
        except (RuntimeError, ValueError):
            return None

    def _raise(self, resp: httpx.Response, op_id: str) -> None:
        status = resp.status_code
        body = self._json(resp)
        code = message = request_id = None
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                code = err.get("code") or err.get("type")
                message = err.get("message")
                request_id = err.get("request_id")
            elif isinstance(err, str):
                message = err
            elif "statusCode" in body or "message" in body:
                message = body.get("message")
        public: Optional[str] = None  # text the SDK wrote itself; the only text that goes into str(error)
        if message is None:
            message = "Request refused" if body is None and status == 404 else resp.reason_phrase or "Error"
            if body is None and status == 404 and len(str(resp.request.url)) > 1900:
                message = "Refused: the request URL is too long. Send fewer ids per request."
                public = message
        if op_id in SANITIZED_ERRORS:
            message = public = f"Request failed (HTTP {status})."
        if status == 401:
            raise AuthError(status, code, message, request_id, public_message=public)
        if status == 404:
            raise NotFoundError(status, code, message, request_id, public_message=public)
        if status == 409:
            exts: list = []
            requested = requested_numbers(self._request_body(resp))
            if op_id in EXTENSION_CONFLICT_OPS or requested:
                exts = extension_conflict_numbers(message or "", requested)
                message = public = EXTENSION_CONFLICT_MESSAGE
            raise ConflictError(status, code, message, request_id, extensions=exts, public_message=public)
        if status in (400, 422):
            raise ValidationError(status, code, message, request_id, public_message=public)
        if status == 429:
            ra = resp.headers.get("Retry-After")
            raise RateLimitError(status, code, message, request_id,
                                 retry_after=float(ra) if ra and ra.replace(".", "", 1).isdigit() else None,
                                 public_message=public)
        raise ApiError(status, code, message, request_id, public_message=public)

    # ------------------------------------------------------------------ operations

    def _build(self, op_id: str, path: Mapping[str, Any], query: Mapping[str, Any], body: Any):
        op = _spec.operation(op_id)
        url_path = op["path"]
        for name in op["path_params"]:
            value = path.get(name)
            if not value or not isinstance(value, str):
                from .errors import InvalidRequestError
                raise InvalidRequestError(f"{op_id}: {name} is required")
            url_path = url_path.replace("{" + name + "}", quote(value, safe=""))
        params = _spec.encode_query(op_id, query)
        if body is not None:
            _spec.check_body(op_id, body)
        elif op["body"] is not None and op["body"]["required"]:
            from .errors import InvalidRequestError
            raise InvalidRequestError(f"{op_id}: a body is required")
        return op, url_path, params

    def _request(self, op_id: str, path: Mapping[str, Any], query: Mapping[str, Any], body: Any,
                 headers: Optional[Dict[str, str]] = None) -> httpx.Response:
        op, url_path, params = self._build(op_id, path, query, body)
        resp = self._send_with_retries(op["method"], url_path, op_id=op_id, params=params,
                                       json_body=dict(body) if body is not None else None, headers=headers)
        if resp.status_code >= 400:
            self._raise(resp, op_id)
        return resp

    def _call(self, op_id: str, *, path: Mapping[str, Any], query: Mapping[str, Any], body: Any,
              headers: Optional[Dict[str, str]] = None) -> Any:
        resp = self._request(op_id, path, query, body, headers)
        if resp.status_code == 204 or not resp.content:
            return None
        return _spec.project_response(op_id, resp.status_code, self._json(resp),
                                      keep_unknown=self.keep_unknown_fields)

    def _page(self, op_id: str, *, path: Mapping[str, Any], query: Mapping[str, Any], body: Any = None) -> Page:
        return Page.from_body(self._call(op_id, path=path, query=query, body=body))

    def _iter(self, op_id: str, *, path: Mapping[str, Any], query: Mapping[str, Any]) -> Iterator[Any]:
        q = dict(query)
        q["limit"] = 100
        cursor: Optional[str] = None
        seen = set()
        while True:
            q["cursor"] = cursor
            page = self._page(op_id, path=path, query=q)
            for item in page.items:
                yield item
            if not page.has_more or not page.next_cursor or page.next_cursor in seen:
                return
            seen.add(page.next_cursor)
            cursor = page.next_cursor

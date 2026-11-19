"""Errors raised by the SDK.

Everything the SDK raises derives from :class:`IntelligenceCloudError`. Errors returned by the API
derive from :class:`ApiError` and carry ``status``, ``code``, ``message`` and ``request_id``.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional

EXTENSION_CONFLICT_MESSAGE = "Extension is already monitored at another location."
MFA_MESSAGE = "Integration users need MFA off for their company. API keys arrive in December 2026."


class IntelligenceCloudError(Exception):
    """Base class for every SDK error."""


class InvalidRequestError(IntelligenceCloudError, ValueError):
    """The request was refused by the SDK before it was sent (unknown filter, bad date, too many ids...)."""


class ApiError(IntelligenceCloudError):
    """The API answered with an error status.

    ``str(error)`` carries only the status, code and request id, plus text the SDK wrote itself
    (``public_message``). The server's own text is on ``message``: it can echo phone numbers or other
    values from the request, so keep it out of logs. Log ``status``, ``code`` and ``request_id``.
    """

    def __init__(self, status: int, code: Optional[str], message: str, request_id: Optional[str] = None,
                 *, public_message: Optional[str] = None):
        self.status = status
        self.code = code
        self.message = message
        self.request_id = request_id
        self.public_message = public_message
        super().__init__(self._text())

    def _text(self) -> str:
        parts = [f"HTTP {self.status}"]
        if self.code:
            parts.append(str(self.code))
        text = " ".join(parts)
        if self.public_message:
            text += f": {self.public_message}"
        if self.request_id:
            text += f" (request_id {self.request_id})"
        return text


class AuthError(ApiError):
    """401: sign-in failed, or the token could not be renewed."""


class PasswordExpiredError(AuthError):
    """The integration user's password has expired. A person sets a new one in the app; then update
    your secret store and sign in again."""


class NotFoundError(ApiError):
    """404. Also returned for records outside your login's scope."""

    def _text(self) -> str:
        return super()._text() + " Not found, or outside what this login can see."


class ConflictError(ApiError):
    """409: duplicate name or email, already active or inactive, or an extension already monitored."""

    def __init__(self, status: int, code: Optional[str], message: str, request_id: Optional[str] = None,
                 extensions: Optional[List[str]] = None, *, public_message: Optional[str] = None):
        self.extensions: List[str] = extensions or []
        super().__init__(status, code, message, request_id, public_message=public_message)


class ValidationError(ApiError):
    """400 or 422: the request was malformed or a value was refused."""


class RateLimitError(ApiError):
    """429 after the SDK's retries ran out."""

    def __init__(self, status: int, code: Optional[str], message: str, request_id: Optional[str] = None,
                 retry_after: Optional[float] = None, *, public_message: Optional[str] = None):
        self.retry_after = retry_after
        super().__init__(status, code, message, request_id, public_message=public_message)


class MfaRequiredError(IntelligenceCloudError):
    """Sign-in returned ``mfa_required``. Integration users need MFA off for their company."""

    def __init__(self, message: str = MFA_MESSAGE):
        super().__init__(message)


class FrontlineRequiredError(IntelligenceCloudError):
    """Conversation data needs a frontline login. Admin logins see empty lists by design."""

    def __init__(self, role: Optional[str]):
        self.role = role
        super().__init__(
            f"This login has role {role!r}. Conversation data (calls, alerts, tasks, insights) needs a "
            "frontline_user login; admin logins get empty lists."
        )


class ConnectorError(IntelligenceCloudError):
    """A connector ended in ``error``. ``state_reason`` says why (for example ``invalid_permissions``)."""

    def __init__(self, connector: Any):
        data = connector if isinstance(connector, dict) else {}
        self.connector = data
        self.connector_id = data.get("id")
        self.status = data.get("status")
        self.state_reason = data.get("state_reason")
        self.status_message = data.get("status_message")
        super().__init__(f"Connector {self.connector_id} is in error: {self.state_reason or 'unknown reason'}")


class ConnectorTimeoutError(IntelligenceCloudError):
    """The connector did not reach a final status in time. Check it again later with get_connector."""

    def __init__(self, connector: Any, waited: float):
        data = connector if isinstance(connector, dict) else {}
        self.connector = data
        self.status = data.get("status")
        super().__init__(f"Connector {data.get('id')} still {self.status!r} after {waited:.0f} s")


class ExtensionMappingError(IntelligenceCloudError):
    """A workflow created or updated the user, but could not map the user's numbers.

    The usual cause is a connector that is not ``active`` yet. Fix the connector, then run the workflow
    again (it finds the user and carries on) or call ``sync_numbers``.
    """

    def __init__(self, user_id: Optional[str], cause: ApiError):
        self.user_id = user_id
        self.cause = cause
        super().__init__(f"User {user_id}: numbers not mapped ({cause}). Number mappings need an active "
                         "connector and extensions no other location monitors.")


class WebhookPayloadError(IntelligenceCloudError, ValueError):
    """The webhook body is not JSON, or is a malformed After Call event. Answer 400."""


class PayloadTooLargeError(WebhookPayloadError):
    """The webhook body is larger than ``max_bytes``. Answer 413."""


_TOKEN_RE = re.compile(r"[0-9*#+]+")


def requested_numbers(body: Any) -> List[str]:
    """Every number listed under ``monitored_numbers`` anywhere in a request body."""
    out: List[str] = []
    if isinstance(body, dict):
        for key, value in body.items():
            if key == "monitored_numbers" and isinstance(value, list):
                out.extend(str(v) for v in value if str(v) not in out)
            else:
                out.extend(n for n in requested_numbers(value) if n not in out)
    elif isinstance(body, list):
        for value in body:
            out.extend(n for n in requested_numbers(value) if n not in out)
    return out


def extension_conflict_numbers(message: str, requested: Optional[List[str]] = None) -> List[str]:
    """The requested extensions that the server's 409 message names. Nothing else from the message
    is kept."""
    wanted = set(requested or [])
    seen: List[str] = []
    for tok in _TOKEN_RE.findall(message or ""):
        if tok in wanted and tok not in seen:
            seen.append(tok)
    return seen

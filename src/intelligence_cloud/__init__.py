"""Intelligence Cloud partner API client.

Customer lifecycle with admin credentials (``client.companies``, ``client.users``, ...,
``client.workflows``) and conversation intelligence with frontline credentials
(``client.intelligence``).
"""
from ._base import Page, unwrap
from ._version import __version__
from .auth import FileTokenStore, MemoryTokenStore, Tokens, TokenStore
from .client import DEFAULT_BASE_URL, Client
from .errors import (
    ApiError,
    AuthError,
    ConflictError,
    ConnectorError,
    ConnectorTimeoutError,
    ExtensionMappingError,
    FrontlineRequiredError,
    IntelligenceCloudError,
    InvalidRequestError,
    MfaRequiredError,
    NotFoundError,
    PasswordExpiredError,
    PayloadTooLargeError,
    RateLimitError,
    ValidationError,
    WebhookPayloadError,
)
from .intelligence import RecordingLink, WebhookTestResult
from .receiver import (
    AfterCallCall,
    AfterCallEvent,
    AfterCallLocation,
    AfterCallSummary,
    Deduplicator,
    DedupStore,
    MAX_EVENT_BYTES,
    MemoryDedupStore,
    UnknownEvent,
    parse_after_call_event,
)
from .workflows import (
    ConnectorSpec,
    LocationSpec,
    SeatCustomer,
    SeatCustomerSpec,
    SeatUser,
    UserSpec,
)

__all__ = [
    "Client", "DEFAULT_BASE_URL", "Page", "unwrap", "__version__",
    "Tokens", "TokenStore", "MemoryTokenStore", "FileTokenStore",
    "IntelligenceCloudError", "InvalidRequestError", "ApiError", "AuthError", "PasswordExpiredError",
    "NotFoundError", "ConflictError", "ValidationError", "RateLimitError", "MfaRequiredError",
    "FrontlineRequiredError", "ConnectorError", "ConnectorTimeoutError", "ExtensionMappingError",
    "WebhookPayloadError", "PayloadTooLargeError", "WebhookTestResult", "RecordingLink",
    "AfterCallEvent", "AfterCallCall", "AfterCallSummary", "AfterCallLocation", "UnknownEvent",
    "parse_after_call_event", "MAX_EVENT_BYTES",
    "Deduplicator", "DedupStore", "MemoryDedupStore",
    "SeatCustomerSpec", "LocationSpec", "ConnectorSpec", "UserSpec", "SeatCustomer", "SeatUser",
]

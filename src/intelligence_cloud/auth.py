"""Token storage. The SDK keeps tokens in memory unless you pass your own ``token_store``."""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Iterator, Optional, Protocol


@dataclass
class Tokens:
    """An access token and its single-use refresh token."""

    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_at: float = 0.0  # epoch seconds; 0 = unknown

    def expired(self, skew: float = 30.0) -> bool:
        return bool(self.expires_at) and time.time() >= self.expires_at - skew

    def __repr__(self) -> str:
        return f"Tokens(access_token='***', refresh_token='***', expires_at={self.expires_at:.0f})"


class TokenStore(Protocol):
    """Where the client keeps its tokens. Implement ``get`` and ``set`` to share tokens between runs.

    Refresh tokens rotate: ``set`` is called with the new pair before it is used, and the old refresh
    token is never sent again. Store it somewhere private (it is a credential).

    **Several processes sharing one integration user** (workers, serverless, a cron next to a web app):
    also implement ``lock()``, returning a context manager that holds a lock across processes. The
    client signs in and renews inside that lock and re-reads the store first, so two processes never
    send the same refresh token (a replayed refresh token ends the session everywhere).
    :class:`FileTokenStore` does this with a lock file; with a shared cache or a database, use its own lock.
    Without ``lock()`` a store is safe only within one process.
    """

    def get(self) -> Optional[Tokens]: ...

    def set(self, tokens: Optional[Tokens]) -> None: ...

    # Optional: def lock(self) -> ContextManager[Any]: ...


class MemoryTokenStore:
    """The default store: tokens live in this process only."""

    def __init__(self, tokens: Optional[Tokens] = None):
        self._tokens = tokens
        self._lock = threading.Lock()

    def get(self) -> Optional[Tokens]:
        with self._lock:
            return self._tokens

    def set(self, tokens: Optional[Tokens]) -> None:
        with self._lock:
            self._tokens = tokens


class FileTokenStore:
    """Tokens in a private file (mode 0600), shared by every process on this machine.

    ``lock()`` takes an exclusive lock on ``<path>.lock`` (``fcntl.flock``; ``msvcrt.locking`` on
    Windows), so processes sharing the file renew one at a time. Writes are atomic.
    """

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self._thread_lock = threading.RLock()

    def get(self) -> Optional[Tokens]:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (FileNotFoundError, ValueError):
            return None
        if not isinstance(data, dict) or not data.get("access_token") or not data.get("refresh_token"):
            return None
        return Tokens(access_token=data["access_token"], refresh_token=data["refresh_token"],
                      expires_at=float(data.get("expires_at") or 0.0))

    def set(self, tokens: Optional[Tokens]) -> None:
        directory = os.path.dirname(self.path) or "."
        if tokens is None:
            with contextlib.suppress(FileNotFoundError):
                os.remove(self.path)
            return
        payload = json.dumps({"access_token": tokens.access_token, "refresh_token": tokens.refresh_token,
                              "expires_at": tokens.expires_at})
        fd, tmp = tempfile.mkstemp(prefix=".tokens-", dir=directory)
        try:
            os.chmod(tmp, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.remove(tmp)
            raise

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        with self._thread_lock:
            fd = os.open(self.path + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
            try:
                _lock_fd(fd)
                try:
                    yield
                finally:
                    _unlock_fd(fd)
            finally:
                os.close(fd)


def _lock_fd(fd: int) -> None:
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows
        import msvcrt
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                return
            except OSError:
                time.sleep(0.05)
    fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock_fd(fd: int) -> None:
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    fcntl.flock(fd, fcntl.LOCK_UN)

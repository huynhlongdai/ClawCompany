"""v26: one Redis connection for the whole process, and a way back from a blip.

Two defects show up only when you read v21 and v22 side by side.

1. ``runtime_leases`` and ``stream_registry`` each called ``redis.from_url``
   at import time. That is two pools per worker for one server, and -- worse
   -- two *independent* opinions about whether Redis exists. A worker could
   hold real shared leases while reporting ``cluster_wide: false``, which is
   exactly the kind of half-truth v22 was written to remove.

2. Both stores set ``self._redis = None`` on the first error and never tried
   again. One network blip demoted a worker to in-process memory *until
   somebody restarted it*, silently, forever. The status endpoint kept saying
   "memory" and was technically right, which is the worst kind of right.

This module owns the connection so there is one answer, and it retries on a
backoff so a blip is a blip rather than a one-way door.
"""

from __future__ import annotations

import os
import random
import socket
import threading
import time
import uuid

from app.core.config import settings

# How long to stay down after a failure before trying to connect again.
# Short enough that a restarted Redis is picked up without operator action,
# long enough that a hard-down Redis is not dialled on every request.
RETRY_SECONDS = 10.0

# v26 retried on a fixed 10s forever, so a hard-down Redis was dialled six
# times a minute per worker -- and every worker retried in lockstep, which
# is a thundering herd the moment Redis comes back. v32 backs off
# exponentially to a ceiling, with jitter to break the lockstep.
MAX_RETRY_SECONDS = 300.0
BACKOFF_FACTOR = 2.0
JITTER_RATIO = 0.2


def backoff_delay(consecutive_failures: int, *, jitter: bool = True) -> float:
    """Delay before the next connect attempt.

    backoff_delay(1) is RETRY_SECONDS, so nothing regresses from v26.
    Callers pass jitter=False when they need a predictable schedule.
    """
    steps = max(0, int(consecutive_failures) - 1)
    delay = min(RETRY_SECONDS * (BACKOFF_FACTOR ** steps), MAX_RETRY_SECONDS)
    if jitter:
        delay *= 1.0 + random.uniform(-JITTER_RATIO, JITTER_RATIO)
    return round(min(delay, MAX_RETRY_SECONDS), 2)

_lock = threading.Lock()


def owner_token() -> str:
    """Identify this process well enough for a human reading Redis directly."""
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class RedisPool:
    """A single lazily-connected client shared by every runtime service."""

    def __init__(self) -> None:
        self.owner = owner_token()
        self._client = None
        self._error = ""
        self._next_attempt = 0.0
        self._attempts = 0
        self._recoveries = 0
        self._failures = 0
        self._consecutive = 0
        self._delay = 0.0
        self._last_failure_at = 0.0
        self._last_success_at = 0.0

    # -- connection --------------------------------------------------------

    def client(self):
        """The shared client, or None while we are in a backoff window.

        Callers must treat None as "not shared right now" and degrade, the
        same contract the per-store clients had. The difference is that None
        is temporary.
        """
        if self._client is not None:
            return self._client
        now = time.time()
        if now < self._next_attempt:
            return None
        with _lock:
            if self._client is not None:
                return self._client
            if time.time() < self._next_attempt:
                return None
            self._attempts += 1
            try:
                import redis  # optional dependency: absent means memory mode

                client = redis.from_url(
                    settings.redis_url,
                    socket_timeout=1,
                    socket_connect_timeout=1,
                    decode_responses=True,
                    max_connections=32,
                )
                client.ping()
            except Exception as exc:  # noqa: BLE001 - degrade, never crash boot
                self._error = str(exc)[:200]
                self._failures += 1
                self._consecutive += 1
                self._delay = backoff_delay(self._consecutive)
                self._last_failure_at = time.time()
                self._next_attempt = self._last_failure_at + self._delay
                return None
            self._client = client
            self._error = ""
            # One success clears the backoff: the next blip starts at 10s
            # again rather than inheriting an hour-old penalty.
            self._consecutive = 0
            self._delay = 0.0
            self._last_success_at = time.time()
            if self._attempts > 1:
                self._recoveries += 1
            return client

    def drop(self, error: str = "") -> None:
        """Mark the connection bad and schedule a retry.

        Stores call this instead of nulling a private handle, so one store
        noticing an outage does not leave another store believing Redis is
        still there.
        """
        with _lock:
            self._client = None
            if error:
                self._error = error[:200]
            self._failures += 1
            self._consecutive += 1
            self._delay = backoff_delay(self._consecutive)
            self._last_failure_at = time.time()
            self._next_attempt = self._last_failure_at + self._delay

    # -- reporting ---------------------------------------------------------

    @property
    def available(self) -> bool:
        return self.client() is not None

    @property
    def backend(self) -> str:
        return "redis" if self.available else "memory"

    def status(self) -> dict:
        available = self.available
        return {
            "backend": "redis" if available else "memory",
            "available": available,
            "owner": self.owner,
            "url": _redacted(settings.redis_url),
            "error": self._error,
            "retry_seconds": RETRY_SECONDS,
            "retry_delay": self._delay,
            "max_retry_seconds": MAX_RETRY_SECONDS,
            "consecutive_failures": self._consecutive,
            "retry_in": max(0.0, round(self._next_attempt - time.time(), 1)) if not available else 0.0,
            "connect_attempts": self._attempts,
            "reconnects": self._recoveries,
            "failures": self._failures,
            "shared_pool": True,
        }


def _redacted(url: str) -> str:
    """Never echo a Redis password back through an API response."""
    if "@" not in url:
        return url
    head, _, tail = url.rpartition("@")
    scheme, sep, _creds = head.partition("://")
    return f"{scheme}{sep}***@{tail}"


pool = RedisPool()

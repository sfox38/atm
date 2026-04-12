"""Per-token sliding window rate limiter for ATM. In-memory only, no I/O."""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass

WINDOW_SECONDS = 60.0
BURST_WINDOW_SECONDS = 1.0


@dataclass
class RateLimitResult:
    """Result of a rate limit check.

    When allowed is True and rate_limiting_enabled is True, the view should
    include X-RateLimit-Limit, X-RateLimit-Remaining, and X-RateLimit-Reset
    response headers.

    When allowed is False, the view should return HTTP 429 with a Retry-After
    header set to retry_after. The X-RateLimit-* headers are omitted on 429.
    """

    allowed: bool
    rate_limiting_enabled: bool
    limit: int = 0
    remaining: int = 0
    reset: int = 0
    retry_after: int = 0


class RateLimiter:
    """Sliding window rate limiter keyed by token ID.

    State is in-memory only and is lost on HA restart. Destroy a token's state
    immediately on revocation or archival by calling destroy(token_id).

    Algorithm per request (when rate limiting is enabled):
      1. Evict timestamps older than WINDOW_SECONDS from the per-token deque.
      2. If len(window) >= rate_limit_requests, return denied. Do not record.
      3. Count timestamps within the last BURST_WINDOW_SECONDS. If that count
         is >= rate_limit_burst (and burst > 0), return denied. Do not record.
      4. Record the current timestamp and return allowed.
    """

    def __init__(self) -> None:
        self._windows: dict[str, deque[float]] = {}

    def check(
        self,
        token_id: str,
        rate_limit_requests: int,
        rate_limit_burst: int,
    ) -> RateLimitResult:
        """Check and record a request against the rate limit for token_id.

        Returns a RateLimitResult with allowed=True if the request may proceed.
        A denied result does NOT record the request in the window.
        """
        if rate_limit_requests == 0:
            return RateLimitResult(allowed=True, rate_limiting_enabled=False)

        now = time.time()
        window_cutoff = now - WINDOW_SECONDS
        burst_cutoff = now - BURST_WINDOW_SECONDS

        if token_id not in self._windows:
            self._windows[token_id] = deque()
        window = self._windows[token_id]

        # Step 1: evict stale entries
        while window and window[0] <= window_cutoff:
            window.popleft()

        # Step 2: sliding window check
        if len(window) >= rate_limit_requests:
            oldest = window[0]
            retry_after = math.ceil(oldest + WINDOW_SECONDS - now)
            return RateLimitResult(
                allowed=False,
                rate_limiting_enabled=True,
                limit=rate_limit_requests,
                remaining=0,
                reset=int(oldest + WINDOW_SECONDS),
                retry_after=max(1, retry_after),
            )

        # Step 3: burst check
        if rate_limit_burst > 0:
            last_second_count = sum(1 for t in window if t > burst_cutoff)
            if last_second_count >= rate_limit_burst:
                oldest_in_burst = next(t for t in window if t > burst_cutoff)
                retry_after = math.ceil(oldest_in_burst + BURST_WINDOW_SECONDS - now)
                reset = int(window[0] + WINDOW_SECONDS) if window else int(now + WINDOW_SECONDS)
                return RateLimitResult(
                    allowed=False,
                    rate_limiting_enabled=True,
                    limit=rate_limit_requests,
                    remaining=max(0, rate_limit_requests - len(window)),
                    reset=reset,
                    retry_after=max(1, retry_after),
                )

        # Step 4: record and return
        window.append(now)
        reset = int(window[0] + WINDOW_SECONDS)
        return RateLimitResult(
            allowed=True,
            rate_limiting_enabled=True,
            limit=rate_limit_requests,
            remaining=rate_limit_requests - len(window),
            reset=reset,
            retry_after=0,
        )

    def destroy(self, token_id: str) -> None:
        """Destroy rate limit state for a single token (call on revocation/archival)."""
        self._windows.pop(token_id, None)

    def destroy_all(self) -> None:
        """Destroy all rate limit state (call on wipe action)."""
        self._windows.clear()

    def active_token_count(self) -> int:
        """Return the number of tokens with active rate limit windows."""
        return len(self._windows)

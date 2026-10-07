from __future__ import annotations

import json
import time
import urllib.request
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from threading import Lock
from typing import Any


class RateLimiter:
    def __init__(self, max_requests: int = 100, period_seconds: float = 60.0) -> None:
        if max_requests < 1 or period_seconds <= 0:
            raise ValueError("rate limit values must be positive")
        self.max_requests = max_requests
        self.period_seconds = period_seconds
        self._requests: deque[float] = deque()
        self._lock = Lock()

    def acquire(self, now: float) -> float:
        with self._lock:
            self._discard_expired(now)
            if len(self._requests) < self.max_requests:
                self._requests.append(now)
                return 0.0
            scheduled = self._requests[0] + self.period_seconds
            wait = max(0.0, scheduled - now)
            self._discard_expired(scheduled)
            self._requests.append(scheduled)
            return wait

    def _discard_expired(self, now: float) -> None:
        boundary = now - self.period_seconds
        while self._requests and self._requests[0] <= boundary:
            self._requests.popleft()


Transport = Callable[[str, dict[str, Any]], Mapping[str, Any]]


class JsonRpcClient:
    def __init__(
        self,
        endpoints: Sequence[str],
        *,
        transport: Transport | None = None,
        limiter: RateLimiter | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts_per_endpoint: int = 2,
    ) -> None:
        if not endpoints:
            raise ValueError("at least one RPC endpoint is required")
        self.endpoints = tuple(endpoints)
        self.transport = transport or _urllib_transport
        self.limiter = limiter or RateLimiter()
        self.clock = clock
        self.sleep = sleep
        self.max_attempts_per_endpoint = max_attempts_per_endpoint
        self._request_id = 0

    def get_receipt(self, tx_hash: str) -> Mapping[str, Any] | None:
        return self.call("eth_getTransactionReceipt", [tx_hash])

    def call(self, method: str, params: list[Any]) -> Any:
        last_error: Exception | None = None
        for endpoint in self.endpoints:
            for attempt in range(self.max_attempts_per_endpoint):
                wait = self.limiter.acquire(self.clock())
                if wait:
                    self.sleep(wait)
                self._request_id += 1
                payload = {
                    "jsonrpc": "2.0",
                    "id": self._request_id,
                    "method": method,
                    "params": params,
                }
                try:
                    response = self.transport(endpoint, payload)
                    if response.get("error"):
                        raise RuntimeError(f"RPC error: {response['error']}")
                    return response.get("result")
                except (OSError, TimeoutError, RuntimeError) as error:
                    last_error = error
                    if attempt + 1 < self.max_attempts_per_endpoint:
                        self.sleep(min(2**attempt, 5))
        raise RuntimeError(f"all RPC endpoints failed: {last_error}") from last_error


def _urllib_transport(endpoint: str, payload: dict[str, Any]) -> Mapping[str, Any]:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))

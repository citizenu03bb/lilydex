"""Bounded sliding-window rate limiters for the web application.

``client_key`` turns a client address into the key a limiter counts against:
IPv4 addresses stay as they are, IPv6 addresses are grouped by their /64 (one
end site, so rotating inside it does not buy fresh counters), and anything that
is not an address is namespaced under ``raw:`` so it can never equal the key of
a real address. The application reads ``request.client.host`` only; trusting a
reverse proxy's forwarded headers is uvicorn's job (see ``manage.py``).

``SlidingWindow`` counts accepted hits per key over a sliding window, under one
lock per limiter. Memory is bounded: keys are kept in least-recently-accepted
order and the oldest are evicted past ``max_keys``. Evicting a key resets its
counter, which is worth at most one fresh window to an attacker, and only
after filling the cap with other live keys, each of which already gave that
same window by simple rotation: eviction adds nothing to what rotation gives.

It is distinct from ``agent_api.RateLimit``, whose limits vary per call.
"""

from __future__ import annotations

import ipaddress
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Hashable

IPV6_PREFIX = 64  # One end site; some providers hand out a /56 or a /48.
MAX_KEYS = 4096  # Read when a limiter is built, so tests can lower it.
RAW_PREFIX = "raw:"
LOCAL = "local"


def _now() -> float:
    """The clock, resolved at call time so tests can patch it."""
    return time.monotonic()


def client_key(host: str | None) -> str:
    """The key a client address counts against."""
    if not host or not host.strip():
        return LOCAL
    text = host.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    text = text.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return RAW_PREFIX + host[:64]
    if isinstance(address, ipaddress.IPv6Address):
        # Before the /64 step, or every mapped IPv4 client would share "::/64".
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network((address, IPV6_PREFIX), strict=False))
    return str(address)


class _Bucket:
    __slots__ = ("stamps", "tags")

    def __init__(self, tagged: bool) -> None:
        self.stamps: deque[float] = deque()
        self.tags: deque[str] | None = deque() if tagged else None


class SlidingWindow:
    """At most ``limit`` accepted hits per key over the last ``window`` seconds.

    A refused hit is not recorded and does not refresh the key's place in the
    eviction order, so that order stays the order of each key's newest hit.
    ``forgive`` can break that order slightly (it may remove a key's newest
    hit); this only delays reclaiming the key, and the cap still holds.
    """

    def __init__(
        self,
        limit: int,
        window: float,
        *,
        max_keys: int | None = None,
        tagged: bool = False,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.limit = limit
        self.window = window
        self.max_keys = MAX_KEYS if max_keys is None else max_keys
        self.tagged = tagged
        self._clock = clock
        self._buckets: OrderedDict[Hashable, _Bucket] = OrderedDict()
        self._lock = threading.Lock()

    def hit(self, key: Hashable, tag: str = "") -> bool:
        """Record a hit for ``key`` and say whether it is allowed."""
        now = (self._clock or _now)()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is not None:
                cutoff = now - self.window
                while bucket.stamps and bucket.stamps[0] <= cutoff:
                    bucket.stamps.popleft()
                    if bucket.tags is not None:
                        bucket.tags.popleft()
                if not bucket.stamps:
                    del self._buckets[key]
                    bucket = None
            if bucket is not None and len(bucket.stamps) >= self.limit:
                return False
            if bucket is None:
                bucket = self._buckets[key] = _Bucket(self.tagged)
            bucket.stamps.append(now)
            if bucket.tags is not None:
                bucket.tags.append(tag)
            self._buckets.move_to_end(key)
            while len(self._buckets) > self.max_keys:
                self._buckets.popitem(last=False)
            return True

    def forgive(self, key: Hashable, tag: str) -> None:
        """Forget ``key``'s hits carrying ``tag``, keeping the others in order."""
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or bucket.tags is None:
                return
            kept = [(s, t) for s, t in zip(bucket.stamps, bucket.tags) if t != tag]
            if not kept:
                del self._buckets[key]
                return
            bucket.stamps = deque(s for s, _ in kept)
            bucket.tags = deque(t for _, t in kept)

    def __len__(self) -> int:
        with self._lock:
            return len(self._buckets)

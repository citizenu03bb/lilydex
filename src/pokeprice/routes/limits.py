"""The web application's rate limiters, built once per application.

The limiters themselves are ``pokeprice.ratelimit.SlidingWindow``; this module
builds the four the routes count against and the ``public_rate`` dependency.
``create_app`` publishes them on ``app.state.rate_limits`` for the tests.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

from ..ratelimit import SlidingWindow, client_key


@dataclass(frozen=True)
class Limits:
    """The limiters and the rate-limit helpers the routes share."""

    failures: SlidingWindow
    public_hits: SlidingWindow
    signups: SlidingWindow
    guests: SlidingWindow
    client_of: Callable[..., Any]
    public_rate: Callable[..., Any]


def build_limits() -> Limits:
    failures = SlidingWindow(5, 300, tagged=True)
    public_hits = SlidingWindow(300, 60)

    def client_of(request: Request) -> str:
        """The rate-limit key of a client: its IPv4 address or its IPv6 /64."""
        return client_key(request.client.host if request.client else None)

    def public_rate(request: Request):
        """Anonymous storefront reads: at most 300 requests a minute per address."""
        key = (client_of(request), "photo" if request.url.path.endswith("/photo") else "api")
        if not public_hits.hit(key):
            raise HTTPException(429, "Trop de requêtes. Réessayez dans une minute.", headers={"Retry-After": "60"})

    signups = SlidingWindow(5, 3600)
    guests = SlidingWindow(5, 3600)
    return Limits(
        failures=failures,
        public_hits=public_hits,
        signups=signups,
        guests=guests,
        client_of=client_of,
        public_rate=public_rate,
    )

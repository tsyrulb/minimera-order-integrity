"""Per-application request limits and HTTP response security headers."""

import time
from collections import deque
from collections.abc import Callable
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .contracts import AppError

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class RateLimiter:
    """Bound request count and peer metadata in a single application worker."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, limit: int = 8) -> None:
        self._clock = clock
        self._limit = limit
        self._peers: dict[str, deque[float]] = {}

    def check(self, peer: str) -> None:
        now = self._clock()
        if peer not in self._peers and len(self._peers) >= 1000:
            self._peers.pop(next(iter(self._peers)))
        recent = self._peers.setdefault(peer, deque())
        while recent and recent[0] <= now - 60:
            recent.popleft()
        if len(recent) >= self._limit:
            raise AppError("RATE_LIMIT", "Please wait a minute before another run.", 429)
        recent.append(now)


def _same_origin(origin: str, host: str, scheme: str) -> bool:
    try:
        parsed = urlsplit(origin)
        return (
            parsed.scheme == scheme
            and parsed.netloc == host
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


class BoundaryMiddleware:
    """Apply limits through ASGI, including to chunked request bodies.

    All response paths, including early rejections, receive the same security
    and API caching headers. Request state is owned by this application worker.
    """

    def __init__(
        self, app: ASGIApp, post_limit: int = 8, body_limit: int = 2048, inline_styles: bool = False
    ) -> None:
        self.app = app
        self._rate = RateLimiter(limit=post_limit)
        self._body_limit = body_limit
        self._headers = SECURITY_HEADERS.copy()
        if inline_styles:
            self._headers["Content-Security-Policy"] = (
                SECURITY_HEADERS["Content-Security-Policy"].replace(
                    "style-src 'self'", "style-src 'self' 'unsafe-inline'"
                )
                + "; object-src 'none'; font-src 'self' data:; worker-src 'self' blob:"
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.update(self._headers)
                if scope["path"].startswith("/api/"):
                    headers["Cache-Control"] = "no-store"
            await send(message)

        if scope["method"] != "POST":
            await self.app(scope, receive, secure_send)
            return
        try:
            body = await self._read_body(receive)
            if body is None:
                return
            headers = Headers(scope=scope)
            origin = headers.get("origin")
            if origin and not _same_origin(origin, headers.get("host", ""), scope["scheme"]):
                raise AppError("ORIGIN_REFUSED", "Use the app from its own page.", 403)
            client = scope.get("client")
            self._rate.check(client[0] if client else "unknown")
        except AppError as exc:
            response = JSONResponse(
                {"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status
            )
            await response(scope, receive, secure_send)
            return
        delivered = False

        async def replay_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, secure_send)

    async def _read_body(self, receive: Receive) -> bytes | None:
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return None
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self._body_limit:
                raise AppError("BODY_TOO_LARGE", "Choose a predefined demo case.", 413)
            body.extend(chunk)
            if not message.get("more_body", False):
                return bytes(body)

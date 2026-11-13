"""The anonymous visitor ID: an HTTP-only cookie that keys saved investigations.

A visitor without a login gets a random ID on the first request. It is the
owner of the investigations they save, so one visitor never sees another's.
The ID is a secret of the browser: it is never logged or put in telemetry.
This is a pure ASGI middleware, not ``BaseHTTPMiddleware``, so server-sent
event streams are passed through untouched and cancel as before.
"""

import re
import uuid
from http.cookies import SimpleCookie

from starlette.types import ASGIApp, Message, Receive, Scope, Send

COOKIE_NAME = "copilot_visitor"
OWNER_PREFIX = "anon:"
_ID = re.compile(r"^[0-9a-f]{32}$")
_SKIP = ("/static/", "/health", "/otlp/")


def owner_of(scope: Scope) -> str | None:
    """The owner key the middleware set for this request, if any."""
    owner = scope.get("state", {}).get("owner")
    return owner if isinstance(owner, str) else None


def _cookie_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"cookie":
            jar: SimpleCookie = SimpleCookie()
            try:
                jar.load(value.decode("latin-1"))
            except Exception:
                return None
            morsel = jar.get(COOKIE_NAME)
            if morsel is not None and _ID.fullmatch(morsel.value):
                return morsel.value
    return None


class VisitorMiddleware:
    def __init__(self, app: ASGIApp, *, max_age_days: float, secure: bool) -> None:
        self.app = app
        self.max_age = int(max_age_days * 86400)
        self.secure = secure

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].startswith(_SKIP):
            await self.app(scope, receive, send)
            return
        visitor = _cookie_id(scope)
        is_new = visitor is None
        if visitor is None:
            visitor = uuid.uuid4().hex
        scope.setdefault("state", {})["owner"] = OWNER_PREFIX + visitor

        async def send_with_cookie(message: Message) -> None:
            if is_new and message["type"] == "http.response.start":
                flags = f"Path=/; Max-Age={self.max_age}; HttpOnly; SameSite=Lax"
                if self.secure:
                    flags += "; Secure"
                headers = list(message.get("headers", []))
                headers.append((b"set-cookie", f"{COOKIE_NAME}={visitor}; {flags}".encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cookie)

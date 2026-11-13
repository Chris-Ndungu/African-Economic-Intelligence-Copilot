"""Cache headers for static files and HTML pages.

Vendored files carry their version in the file name, so they may be cached for
a year. The app's own static files and every HTML page are revalidated, so a
deploy shows at once. A response that already sets ``Cache-Control`` (such as
an event stream) keeps its own.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

IMMUTABLE = b"public, max-age=31536000, immutable"
NO_CACHE = b"no-cache"


class CacheControlMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]

        async def send_with_cache(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                names = {name.lower() for name, _ in headers}
                if b"cache-control" not in names:
                    content_type = dict(headers).get(b"content-type", b"")
                    if path.startswith("/static/vendor/") and message["status"] == 200:
                        headers.append((b"cache-control", IMMUTABLE))
                    elif path.startswith("/static/") or content_type.startswith(b"text/html"):
                        headers.append((b"cache-control", NO_CACHE))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cache)

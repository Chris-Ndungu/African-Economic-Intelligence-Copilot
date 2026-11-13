"""The address of the client that made a request, for the rate limit.

``X-Forwarded-For`` is a list the client can start with any values; every
proxy in front of the app appends the address it saw. So the only trustworthy
entry is the one the app's own front end appended: the ``hops``-th from the
right. Entries to its left are client-supplied and ignored. With ``hops`` of
0 there is no trusted proxy, and the header is ignored altogether.
"""

import ipaddress

from starlette.requests import Request


def client_ip(request: Request, hops: int) -> str:
    if hops > 0:
        header = request.headers.get("x-forwarded-for", "")
        entries = [e.strip() for e in header.split(",") if e.strip()]
        if len(entries) >= hops:
            candidate = entries[-hops]
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                pass  # not an address: fall back to the connection's peer
    return request.client.host if request.client else "unknown"

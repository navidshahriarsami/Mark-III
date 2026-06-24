"""
MARK III Brain Server — Request Logging Middleware

Logs every inbound request with method, path, device ID (from header),
response status, and latency. Output is structured so it's easy to
grep for a specific device_id in production.
"""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("markiii.server.request")


class RequestLogMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next) -> Response:
        t0        = time.perf_counter()
        device_id = request.headers.get("X-Device-ID", "-")[:16]
        agent     = request.headers.get("X-Agent",     "-")

        response  = await call_next(request)

        latency_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "%s %s %d  %.1f ms  device=%s  agent=%s",
            request.method,
            request.url.path,
            response.status_code,
            latency_ms,
            device_id,
            agent,
        )
        return response

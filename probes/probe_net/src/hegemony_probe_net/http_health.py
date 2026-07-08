# SPDX-FileCopyrightText: 2025-2026 Jakub Trávník <jakub.travnik@gmail.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""HTTP health probe.

GETs ``http://<address>[:port]<url_path>`` and reports ok for any status below
400. The richer one-shot variant (https, methods, status specs, body matching)
lives in the ``probe.http`` step handler.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from hegemony_step_sdk import BaseProbe, ProbeResult

logger = logging.getLogger(__name__)


class HttpHealthProbe(BaseProbe):
    """HTTP health probe.

    Options:
        port: TCP port (default: 80)
        url_path: Request path (default: /health)
        timeout_ms: Request timeout in milliseconds (default: 5000)

    Metrics produced:
        connect_ms: Total request time
        http_status: Response status code
    """

    probe_id = "http_health"

    async def execute(self, address: str, options: dict[str, Any]) -> ProbeResult:
        port = options.get("port")
        url_path = options.get("url_path") or "/health"
        if not url_path.startswith("/"):
            url_path = "/" + url_path
        timeout_sec = options.get("timeout_ms", 5000) / 1000.0

        netloc = address if port in (None, 80) else f"{address}:{port}"
        url = f"http://{netloc}{url_path}"

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
                response = await client.get(url)
        except httpx.TimeoutException:
            elapsed = (time.perf_counter() - start) * 1000
            return ProbeResult(
                ok=False,
                metrics={"connect_ms": round(elapsed, 3)},
                error_kind="timeout",
                error_detail=f"Request timed out after {timeout_sec}s",
            )
        except httpx.HTTPError as exc:
            elapsed = (time.perf_counter() - start) * 1000
            return ProbeResult(
                ok=False,
                metrics={"connect_ms": round(elapsed, 3)},
                error_kind="http_error",
                error_detail=f"{type(exc).__name__}: {exc}",
            )

        elapsed = (time.perf_counter() - start) * 1000
        metrics = {"connect_ms": round(elapsed, 3), "http_status": response.status_code}
        if response.status_code >= 400:
            return ProbeResult(
                ok=False,
                metrics=metrics,
                error_kind="http_status",
                error_detail=f"HTTP {response.status_code}",
            )
        return ProbeResult(ok=True, metrics=metrics)

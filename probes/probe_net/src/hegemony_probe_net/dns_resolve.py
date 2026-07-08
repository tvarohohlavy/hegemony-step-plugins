# SPDX-FileCopyrightText: 2025-2026 Jakub Trávník <jakub.travnik@gmail.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""DNS resolution probe.

Resolves a hostname (the ``hostname`` option, falling back to the target
address) via the system resolver. Record types, custom resolvers, and
expected-answer assertions live in the ``probe.dns`` step handler.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from typing import Any

from hegemony_step_sdk import BaseProbe, ProbeResult

logger = logging.getLogger(__name__)


class DnsResolveProbe(BaseProbe):
    """DNS resolution probe using the system resolver.

    Options:
        hostname: Name to resolve (default: the target address)
        timeout_ms: Resolution timeout in milliseconds (default: 5000)

    Metrics produced:
        resolve_ms: Resolution time
        addresses: Number of resolved addresses
    """

    probe_id = "dns_resolve"

    async def execute(self, address: str, options: dict[str, Any]) -> ProbeResult:
        hostname = (options.get("hostname") or "").strip() or address
        timeout_sec = options.get("timeout_ms", 5000) / 1000.0

        loop = asyncio.get_running_loop()
        start = time.perf_counter()
        try:
            infos = await asyncio.wait_for(
                loop.getaddrinfo(hostname, None, type=socket.SOCK_STREAM),
                timeout=timeout_sec,
            )
        except TimeoutError:
            elapsed = (time.perf_counter() - start) * 1000
            return ProbeResult(
                ok=False,
                metrics={"resolve_ms": round(elapsed, 3)},
                error_kind="timeout",
                error_detail=f"Resolution timed out after {timeout_sec}s",
            )
        except socket.gaierror as exc:
            elapsed = (time.perf_counter() - start) * 1000
            return ProbeResult(
                ok=False,
                metrics={"resolve_ms": round(elapsed, 3)},
                error_kind="resolution_failed",
                error_detail=str(exc),
            )

        elapsed = (time.perf_counter() - start) * 1000
        addresses = sorted({info[4][0] for info in infos})
        return ProbeResult(
            ok=bool(addresses),
            metrics={"resolve_ms": round(elapsed, 3), "addresses": len(addresses)},
            error_kind=None if addresses else "no_answers",
            error_detail=None if addresses else f"no addresses for {hostname}",
        )

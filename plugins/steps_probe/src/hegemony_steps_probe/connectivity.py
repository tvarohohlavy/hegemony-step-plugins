# SPDX-FileCopyrightText: 2025-2026 Jakub Trávník <jakub.travnik@gmail.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ConnectivityCheckHandler: one-shot connectivity probes against targets.

Self-contained: carries its own tcp/icmp probe implementations (stdlib only)
so it does not depend on the platform's monitor subsystem. The platform's
background monitors keep their own copy of these probes — the handler is the
one-shot flow-step variant.
"""

import asyncio
import logging
import platform as _platform
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from hegemony_step_sdk import (
    BaseHandler,
    HandlerContext,
    HandlerResult,
    StepKind,
)

logger = logging.getLogger(__name__)

#: Check types accepted by the flow engine (validated before probing).
KNOWN_CHECK_TYPES = frozenset(
    {"tcp_connect", "icmp_ping", "dns_resolve", "http_health", "tls_handshake", "ssh_banner"}
)
#: Check types this handler can actually execute today.
IMPLEMENTED_CHECK_TYPES = frozenset({"tcp_connect", "icmp_ping", "http_health", "dns_resolve"})

# Regex patterns for parsing ping output
LINUX_RTT_PATTERN = re.compile(r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms")
WINDOWS_RTT_PATTERN = re.compile(r"Minimum = (\d+)ms, Maximum = (\d+)ms, Average = (\d+)ms")
LINUX_SINGLE_RTT = re.compile(r"time=([\d.]+)\s*ms")
WINDOWS_SINGLE_RTT = re.compile(r"time[<=]([\d.]+)ms")


@dataclass
class ProbeResult:
    """Result of a single probe against one target."""

    ok: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    error_kind: str | None = None
    error_detail: str | None = None
    raw_text: str | None = None


async def _tcp_connect_probe(address: str, options: dict[str, Any]) -> ProbeResult:
    """TCP connection probe measuring connect time."""
    port = options.get("port")
    if port is None:
        return ProbeResult(
            ok=False,
            error_kind="config_error",
            error_detail="port is required for tcp_connect check",
        )

    timeout_ms = options.get("timeout_ms", 5000)
    timeout_sec = timeout_ms / 1000.0
    start_time = time.perf_counter()

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(address, port),
            timeout=timeout_sec,
        )
        connect_time = (time.perf_counter() - start_time) * 1000  # ms
        writer.close()
        await writer.wait_closed()
        return ProbeResult(
            ok=True,
            metrics={"connect_ms": round(connect_time, 3), "port": port},
        )

    except TimeoutError:
        elapsed = (time.perf_counter() - start_time) * 1000
        return ProbeResult(
            ok=False,
            metrics={"connect_ms": round(elapsed, 3), "port": port},
            error_kind="timeout",
            error_detail=f"Connection timed out after {timeout_ms}ms",
        )

    except ConnectionRefusedError:
        elapsed = (time.perf_counter() - start_time) * 1000
        return ProbeResult(
            ok=False,
            metrics={"connect_ms": round(elapsed, 3), "port": port},
            error_kind="connection_refused",
            error_detail=f"Connection refused on port {port}",
        )

    except OSError as e:
        elapsed = (time.perf_counter() - start_time) * 1000
        error_kind = "network_error"
        if "Network is unreachable" in str(e):
            error_kind = "network_unreachable"
        elif "No route to host" in str(e):
            error_kind = "no_route"
        elif "Host is down" in str(e):
            error_kind = "host_down"
        return ProbeResult(
            ok=False,
            metrics={"connect_ms": round(elapsed, 3), "port": port},
            error_kind=error_kind,
            error_detail=str(e),
        )

    except Exception as e:
        logger.exception(f"TCP connect check failed for {address}:{port}")
        elapsed = (time.perf_counter() - start_time) * 1000
        return ProbeResult(
            ok=False,
            metrics={"connect_ms": round(elapsed, 3), "port": port},
            error_kind="exception",
            error_detail=str(e),
        )


def _calculate_jitter(rtt_values: list[float]) -> float | None:
    """Mean absolute difference between consecutive RTT samples (RFC 3550 simplified)."""
    if len(rtt_values) < 2:
        return None
    diffs = [abs(rtt_values[i + 1] - rtt_values[i]) for i in range(len(rtt_values) - 1)]
    return sum(diffs) / len(diffs)


def _extract_individual_rtts(output: str, is_windows: bool) -> list[float]:
    pattern = WINDOWS_SINGLE_RTT if is_windows else LINUX_SINGLE_RTT
    return [float(match.group(1)) for match in pattern.finditer(output)]


def _parse_ping_output(output: str, return_code: int | None, is_windows: bool) -> ProbeResult:
    """Parse ping command output to extract metrics."""
    metrics: dict[str, Any] = {}
    individual_rtts = _extract_individual_rtts(output, is_windows)

    if is_windows:
        match = WINDOWS_RTT_PATTERN.search(output)
        if match:
            metrics["rtt_min_ms"] = float(match.group(1))
            metrics["rtt_max_ms"] = float(match.group(2))
            metrics["rtt_ms"] = float(match.group(3))
        elif individual_rtts:
            metrics["rtt_ms"] = individual_rtts[-1]
    else:
        match = LINUX_RTT_PATTERN.search(output)
        if match:
            metrics["rtt_min_ms"] = float(match.group(1))
            metrics["rtt_ms"] = float(match.group(2))  # avg
            metrics["rtt_max_ms"] = float(match.group(3))
            metrics["rtt_mdev_ms"] = float(match.group(4))
        elif individual_rtts:
            metrics["rtt_ms"] = individual_rtts[-1]

    if len(individual_rtts) >= 2:
        jitter = _calculate_jitter(individual_rtts)
        if jitter is not None:
            metrics["jitter_ms"] = round(jitter, 3)
    elif "rtt_mdev_ms" in metrics:
        metrics["jitter_ms"] = metrics["rtt_mdev_ms"]

    sent_match = re.search(r"(\d+)\s*packets?\s*(?:transmitted|Sent)", output, re.I)
    recv_match = re.search(r"(\d+)\s*(?:packets?\s*)?received", output, re.I)
    loss_match = re.search(r"(\d+(?:\.\d+)?)[%]\s*(?:packet\s*)?loss", output, re.I)

    if sent_match:
        metrics["packets_sent"] = int(sent_match.group(1))
    if recv_match:
        metrics["packets_received"] = int(recv_match.group(1))
    if loss_match:
        metrics["packet_loss_pct"] = float(loss_match.group(1))

    ok = return_code == 0 and metrics.get("packets_received", 0) > 0

    if not ok and not metrics:
        error_detail = output.strip()[:500] if output else "No response"
        return ProbeResult(
            ok=False,
            error_kind="no_response",
            error_detail=error_detail,
            raw_text=output,
        )

    return ProbeResult(
        ok=ok,
        metrics=metrics,
        raw_text=output if not ok else None,
        error_kind="packet_loss" if not ok else None,
        error_detail=f"{metrics.get('packet_loss_pct', 100)}% packet loss" if not ok else None,
    )


async def _icmp_ping_probe(address: str, options: dict[str, Any]) -> ProbeResult:
    """ICMP ping probe using the system ping command."""
    count = options.get("count", 1)
    timeout_ms = options.get("timeout_ms", 1000)
    timeout_sec = timeout_ms / 1000.0

    is_windows = _platform.system().lower() == "windows"
    if is_windows:
        cmd = ["ping", "-n", str(count), "-w", str(timeout_ms), address]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(max(1, int(timeout_sec))), address]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_sec * count + 5,  # Extra buffer
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            return ProbeResult(
                ok=False,
                error_kind="timeout",
                error_detail=f"Ping command timed out after {timeout_sec * count + 5}s",
            )

        output = stdout.decode("utf-8", errors="replace")
        return _parse_ping_output(output, process.returncode, is_windows)

    except FileNotFoundError:
        return ProbeResult(
            ok=False,
            error_kind="command_not_found",
            error_detail="ping command not found on system",
        )
    except Exception as e:
        logger.exception(f"Ping check failed for {address}")
        return ProbeResult(
            ok=False,
            error_kind="exception",
            error_detail=str(e),
        )


async def _http_health_probe(address: str, options: dict[str, Any]) -> ProbeResult:
    """Basic HTTP health probe: GET http://address[:port]<url_path>, ok on status < 400.

    The dedicated ``probe.http`` handler offers the richer contract (https,
    methods, status specs, body matching); this keeps the connectivity
    handler's advertised ``http_health`` check type working.
    """
    import httpx

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
    except httpx.HTTPError as exc:
        return ProbeResult(
            ok=False,
            error_kind="http_error",
            error_detail=f"{type(exc).__name__}: {exc}",
        )
    latency = round((time.perf_counter() - start) * 1000, 3)
    metrics = {"connect_ms": latency, "http_status": response.status_code}
    if response.status_code >= 400:
        return ProbeResult(
            ok=False,
            metrics=metrics,
            error_kind="http_status",
            error_detail=f"HTTP {response.status_code}",
        )
    return ProbeResult(ok=True, metrics=metrics)


async def _dns_resolve_probe(address: str, options: dict[str, Any]) -> ProbeResult:
    """Basic DNS probe: resolve ``options['hostname']`` (fallback: the address) as A.

    The dedicated ``probe.dns`` handler offers record types, custom resolvers,
    and expected-answer assertions.
    """
    import dns.exception

    from .dns_check import resolve_records

    hostname = (options.get("hostname") or "").strip() or address
    timeout_sec = options.get("timeout_ms", 5000) / 1000.0

    start = time.perf_counter()
    try:
        answers = await resolve_records(hostname, "A", timeout_sec=timeout_sec)
    except (dns.exception.DNSException, OSError) as exc:
        return ProbeResult(
            ok=False,
            error_kind="dns_error",
            error_detail=f"{type(exc).__name__}: {exc}",
        )
    latency = round((time.perf_counter() - start) * 1000, 3)
    return ProbeResult(
        ok=bool(answers),
        metrics={"connect_ms": latency, "answers": len(answers)},
        error_kind=None if answers else "no_answers",
        error_detail=None if answers else f"no A records for {hostname}",
    )


async def _execute_probe(check_type: str, address: str, options: dict[str, Any]) -> ProbeResult:
    """Run one probe; raises ``KeyError`` for known-but-unimplemented check types."""
    if check_type == "tcp_connect":
        return await _tcp_connect_probe(address, options)
    if check_type == "icmp_ping":
        return await _icmp_ping_probe(address, options)
    if check_type == "http_health":
        return await _http_health_probe(address, options)
    if check_type == "dns_resolve":
        return await _dns_resolve_probe(address, options)
    raise KeyError(f"Check not registered: {check_type}")


class ConnectivityCheckConfig(BaseModel):
    """Config for ``probe.connectivity``."""

    model_config = ConfigDict(extra="allow")

    check_type: Literal["tcp_connect", "icmp_ping", "http_health", "dns_resolve"] = Field(
        default="tcp_connect",
        title="Check Type",
        json_schema_extra={
            "x_option_labels": {
                "tcp_connect": "TCP Connect",
                "icmp_ping": "ICMP Ping",
                "http_health": "HTTP Health",
                "dns_resolve": "DNS Resolve",
            }
        },
    )
    port: int = Field(
        default=22,
        ge=1,
        le=65535,
        title="Port",
        description="For TCP/TLS/SSH checks",
        json_schema_extra={
            "x_placeholder": "22",
            "x_hide_when": {"field": "check_type", "value": "icmp_ping"},
        },
    )
    timeout_sec: int = Field(default=10, ge=1, title="Timeout (sec)")
    attempts: int = Field(
        default=1, ge=1, le=10, title="Attempts", description="Number of attempts (1-10)"
    )
    url_path: str = Field(
        default="",
        title="URL Path",
        json_schema_extra={
            "x_placeholder": "/health",
            "x_show_when": {"field": "check_type", "value": "http_health"},
            "x_col_span": 2,
        },
    )
    hostname: str = Field(
        default="",
        title="Hostname to Resolve",
        json_schema_extra={
            "x_placeholder": "device.example.com",
            "x_show_when": {"field": "check_type", "value": "dns_resolve"},
            "x_col_span": 2,
        },
    )


class ConnectivityCheckHandler(BaseHandler):
    """Unified connectivity check handler.

    Performs single or few connectivity checks against targets and
    emits results as evidence.

    Config:
        check_type: str - Type of check (default: tcp_connect)
        port: int - Target port (default: 22)
        timeout_sec: int - Timeout per attempt (default: 10)
        attempts: int - Number of attempts (default: 1)
        url_path: str - For http_health, the URL path (default: /health)
        hostname: str - For dns_resolve, hostname to resolve
    """

    handler_id = "probe.connectivity"
    supported_kinds = [StepKind.CHECK]
    display_name = "Connectivity Check"
    description = "One-shot connectivity probes (TCP/ICMP/HTTP/DNS) against targets."
    category = "Checks"
    config_model = ConnectivityCheckConfig
    default_config = {"check_type": "tcp_connect", "port": 22, "timeout_sec": 10, "attempts": 1}

    async def execute(self, ctx: HandlerContext) -> HandlerResult:
        """Run connectivity check against all target devices."""
        target_devices = ctx.get_target_devices()
        if not target_devices:
            return HandlerResult(
                success=False,
                error="No target devices configured",
                summary="Missing target device",
            )

        check_type = ctx.config.get("check_type", "tcp_connect")
        port = ctx.config.get("port", 22)
        timeout_sec = ctx.config.get("timeout_sec", 10)
        attempts = min(ctx.config.get("attempts", 1), 10)

        # Build check options based on type
        options: dict[str, Any] = {
            "timeout_ms": timeout_sec * 1000,
        }

        if check_type == "tcp_connect":
            options["port"] = port
        elif check_type == "http_health":
            options["port"] = port
            options["url_path"] = ctx.config.get("url_path", "/health")
        elif check_type == "tls_handshake" or check_type == "ssh_banner":
            options["port"] = port
        elif check_type == "icmp_ping":
            options["count"] = 1
        elif check_type == "dns_resolve":
            options["hostname"] = ctx.config.get("hostname", "")

        # Validate check type
        if check_type not in KNOWN_CHECK_TYPES:
            return HandlerResult(
                success=False,
                error=f"Invalid check_type: {check_type}",
                summary=f"Unknown check type: {check_type}",
            )

        all_evidence = []
        all_metrics = {}
        failed_devices = []
        success_count = 0

        for device in target_devices:
            device_id = device.get("id", "unknown")
            device_name = device.get("name", device_id)
            host = device.get("mgmt_host")

            if not host:
                failed_devices.append(f"{device_name} (no host)")
                continue

            # Run checks with attempts
            best_result: ProbeResult | None = None
            for attempt in range(attempts):
                result = await _execute_probe(check_type, host, options)
                if result.ok:
                    best_result = result
                    break
                best_result = result
                if attempt < attempts - 1:
                    await asyncio.sleep(0.5)  # Brief pause between retries

            if best_result and best_result.ok:
                success_count += 1
                # Extract primary metric
                metric_key = f"{device_name}_ms"
                if "rtt_ms" in best_result.metrics:
                    all_metrics[metric_key] = best_result.metrics["rtt_ms"]
                elif "connect_ms" in best_result.metrics:
                    all_metrics[metric_key] = best_result.metrics["connect_ms"]

                all_evidence.append(
                    {
                        "kind": "transport_meta",
                        "name": f"connectivity_{check_type}_{device_name}",
                        "device_id": device_id,
                        "content_json": {
                            "device_id": device_id,
                            "device_name": device_name,
                            "host": host,
                            "check_type": check_type,
                            "success": True,
                            "metrics": best_result.metrics,
                        },
                    }
                )
            else:
                error_msg = best_result.error_detail if best_result else "unknown error"
                failed_devices.append(f"{device_name} ({error_msg})")
                all_evidence.append(
                    {
                        "kind": "transport_meta",
                        "name": f"connectivity_{check_type}_{device_name}",
                        "device_id": device_id,
                        "content_json": {
                            "device_id": device_id,
                            "device_name": device_name,
                            "host": host,
                            "check_type": check_type,
                            "success": False,
                            "error": error_msg,
                        },
                    }
                )

        total = len(target_devices)
        if failed_devices:
            return HandlerResult(
                success=False,
                error=f"Failed: {', '.join(failed_devices)}",
                summary=f"{check_type}: {success_count}/{total} devices OK",
                metrics=all_metrics,
                evidence=all_evidence,
            )

        return HandlerResult(
            success=True,
            summary=f"{check_type}: {success_count}/{total} devices OK",
            metrics=all_metrics,
            evidence=all_evidence,
        )

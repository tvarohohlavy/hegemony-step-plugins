# SPDX-FileCopyrightText: 2025-2026 Jakub Trávník <jakub.travnik@gmail.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""DnsProbeHandler: DNS resolution checks."""

import asyncio
import logging
import time
from typing import Any, Literal

import dns.asyncresolver
import dns.exception
from pydantic import BaseModel, ConfigDict, Field

from hegemony_step_sdk import BaseHandler, HandlerContext, HandlerResult, StepKind

logger = logging.getLogger(__name__)


def normalize_answer(value: str) -> str:
    """Normalize one DNS answer for comparison (lowercase, no trailing dot/quotes)."""
    return value.strip().strip('"').rstrip(".").lower()


async def resolve_records(
    query_name: str,
    record_type: str,
    *,
    resolver_ip: str = "",
    timeout_sec: float = 5.0,
) -> list[str]:
    """Resolve ``query_name``/``record_type``; returns normalized answer strings.

    Raises ``dns.exception.DNSException`` on resolution failure.
    """
    resolver = dns.asyncresolver.Resolver()
    if resolver_ip:
        resolver.nameservers = [resolver_ip]
    resolver.lifetime = timeout_sec
    answer = await resolver.resolve(query_name, record_type)
    return sorted(normalize_answer(rdata.to_text()) for rdata in answer)


class DnsProbeConfig(BaseModel):
    """Config for ``probe.dns``."""

    model_config = ConfigDict(extra="allow")

    query_name: str = Field(
        default="",
        title="Name to Resolve",
        description="Leave empty to resolve each target device's hostname",
        json_schema_extra={"x_placeholder": "device.example.com", "x_col_span": 2},
    )
    record_type: Literal["A", "AAAA", "CNAME", "MX", "NS", "TXT"] = Field(
        default="A", title="Record Type"
    )
    resolver: str = Field(
        default="",
        title="Resolver (optional)",
        description="Nameserver IP; empty uses the system resolver",
        json_schema_extra={"x_placeholder": "192.0.2.53"},
    )
    expected_values: list[str] = Field(
        default_factory=list,
        title="Expected Values (optional)",
        description="One per line; every listed value must appear in the answers",
        json_schema_extra={
            "x_widget": "commands",
            "x_rows": 3,
            "x_col_span": 2,
            "x_placeholder": "192.0.2.10\n192.0.2.11",
        },
    )
    timeout_sec: int = Field(default=5, ge=1, title="Timeout (sec)")
    attempts: int = Field(
        default=1, ge=1, le=10, title="Attempts", description="Number of attempts (1-10)"
    )


class DnsProbeHandler(BaseHandler):
    """DNS resolution check, per target device or for an explicit name."""

    handler_id = "probe.dns"
    supported_kinds = [StepKind.CHECK]
    display_name = "DNS Check"
    description = "Resolve a DNS name (or each target's hostname) and assert the answers."
    category = "Checks"
    config_model = DnsProbeConfig
    default_config = {"record_type": "A", "timeout_sec": 5}

    async def execute(self, ctx: HandlerContext) -> HandlerResult:
        target_devices = ctx.get_target_devices()
        if not target_devices:
            return HandlerResult(
                success=False,
                error="No target devices configured",
                summary="Missing target device",
            )

        configured_name = str(ctx.config.get("query_name", "") or "").strip()
        record_type = ctx.config.get("record_type", "A")
        resolver_ip = str(ctx.config.get("resolver", "") or "").strip()
        timeout_sec = ctx.config.get("timeout_sec", 5)
        attempts = min(int(ctx.config.get("attempts", 1)), 10)
        expected = [
            normalize_answer(str(value))
            for value in ctx.config.get("expected_values", []) or []
            if str(value).strip()
        ]

        all_evidence: list[dict[str, Any]] = []
        all_metrics: dict[str, Any] = {}
        failed_devices: list[str] = []
        success_count = 0

        for device in target_devices:
            device_id = device.get("id", "unknown")
            device_name = device.get("name", device_id)
            query_name = configured_name or device.get("hostname") or device.get("mgmt_host")
            if not query_name:
                failed_devices.append(f"{device_name} (no name to resolve)")
                continue

            answers: list[str] = []
            error: str | None = None
            latency_ms: float | None = None
            for attempt in range(attempts):
                start = time.perf_counter()
                try:
                    answers = await resolve_records(
                        query_name,
                        record_type,
                        resolver_ip=resolver_ip,
                        timeout_sec=float(timeout_sec),
                    )
                    latency_ms = round((time.perf_counter() - start) * 1000, 3)
                    error = None
                    break
                except dns.exception.DNSException as exc:
                    error = f"{type(exc).__name__}: {exc}"
                except OSError as exc:
                    error = str(exc)
                if attempt < attempts - 1:
                    await asyncio.sleep(0.5)

            missing = [value for value in expected if value not in answers]
            ok = error is None and not missing
            if ok:
                success_count += 1
                if latency_ms is not None:
                    all_metrics[f"{device_name}_ms"] = latency_ms
            elif error is not None:
                failed_devices.append(f"{device_name} ({error})")
            else:
                failed_devices.append(f"{device_name} (missing: {', '.join(missing)})")

            all_evidence.append(
                {
                    "kind": "transport_meta",
                    "name": f"dns_{record_type}_{device_name}",
                    "device_id": device_id,
                    "content_json": {
                        "device_id": device_id,
                        "device_name": device_name,
                        "query_name": query_name,
                        "record_type": record_type,
                        "resolver": resolver_ip or "system",
                        "success": ok,
                        "answers": answers,
                        "missing_expected": missing,
                        "error": error,
                    },
                }
            )

        total = len(target_devices)
        summary = f"dns {record_type}: {success_count}/{total} lookups OK"
        if failed_devices:
            return HandlerResult(
                success=False,
                error=f"Failed: {', '.join(failed_devices)}",
                summary=summary,
                metrics=all_metrics,
                evidence=all_evidence,
            )
        return HandlerResult(
            success=True, summary=summary, metrics=all_metrics, evidence=all_evidence
        )

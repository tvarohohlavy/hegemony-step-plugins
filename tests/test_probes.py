# SPDX-FileCopyrightText: 2025-2026 Jakub Trávník <jakub.travnik@gmail.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Registration and behavior tests for the hegemony-probe-net wheel."""

import hegemony_probe_net
from hegemony_step_sdk import BaseProbe, ProbeResult

EXPECTED_PROBE_IDS = {"tcp_connect", "icmp_ping", "http_health", "dns_resolve"}


def test_all_probes_are_base_probes_with_ids():
    ids = set()
    for cls in hegemony_probe_net.ALL_PROBES:
        assert issubclass(cls, BaseProbe), cls.__name__
        assert cls.probe_id, cls.__name__
        ids.add(cls.probe_id)
    assert ids == EXPECTED_PROBE_IDS


def test_register_populates_a_registry():
    registered: list[type] = []

    class _Registry:
        def register_probe(self, probe_class: type) -> None:
            registered.append(probe_class)

    hegemony_probe_net.register(_Registry())
    assert set(registered) == set(hegemony_probe_net.ALL_PROBES)


def test_tcp_connect_requires_port():
    from hegemony_probe_net.tcp_connect import TcpConnectProbe

    async def run() -> ProbeResult:
        return await TcpConnectProbe().execute("192.0.2.1", {})

    import asyncio

    result = asyncio.run(run())
    assert result.ok is False
    assert result.error_kind == "config_error"


async def test_tcp_connect_connection_refused():
    from hegemony_probe_net.tcp_connect import TcpConnectProbe

    # localhost:1 is almost certainly closed → fast refusal.
    result = await TcpConnectProbe().execute("127.0.0.1", {"port": 1, "timeout_ms": 2000})
    assert result.ok is False
    assert result.error_kind in {"connection_refused", "timeout", "network_error"}


async def test_dns_resolve_localhost():
    from hegemony_probe_net.dns_resolve import DnsResolveProbe

    result = await DnsResolveProbe().execute("localhost", {"timeout_ms": 2000})
    assert result.ok is True
    assert result.metrics.get("addresses", 0) >= 1

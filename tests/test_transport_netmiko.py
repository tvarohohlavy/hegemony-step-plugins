# SPDX-FileCopyrightText: 2025-2026 Jakub Trávník <jakub.travnik@gmail.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for the netmiko device transport wheel.

Covers registration under hegemony.device_transports, spec-based construction,
and config-set result building (regression: the full send_config_set session
output must attach to exactly one result, not every entry equal to the trailing
command).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import hegemony_transport_netmiko
from hegemony_step_sdk import DeviceConnectionSpec
from hegemony_transport_netmiko.transport import SSHTransport, _NullCancellationRegistry


def test_register_registers_the_netmiko_transport():
    registered: list[type] = []

    class _Registry:
        def register_transport(self, transport_class: type) -> None:
            registered.append(transport_class)

    hegemony_transport_netmiko.register(_Registry())
    assert registered == [SSHTransport]
    assert SSHTransport.transport_id == "netmiko"


def test_construct_from_spec_resolves_fields():
    spec = DeviceConnectionSpec(
        host="10.0.0.1",
        port=2022,
        username="admin",
        password="pw",
        enable_secret="en",
        platform="ios-xe",
    )
    with patch.object(hegemony_transport_netmiko.transport, "ConnectHandler", MagicMock()):
        t = SSHTransport(spec)
    assert t.host == "10.0.0.1"
    assert t.port == 2022
    assert t.username == "admin"
    assert t.device_type == "cisco_ios"
    assert isinstance(t._cancellation_registry, _NullCancellationRegistry)


def test_construct_requires_username():
    import pytest

    spec = DeviceConnectionSpec(host="10.0.0.1", username="")
    with (
        patch.object(hegemony_transport_netmiko.transport, "ConnectHandler", MagicMock()),
        pytest.raises(ValueError, match="username"),
    ):
        SSHTransport(spec)


def _make_transport() -> SSHTransport:
    """Build an SSHTransport without running the connecting __init__."""
    t = SSHTransport.__new__(SSHTransport)
    t.host = "10.0.0.1"
    t.port = 22
    t.platform = "ios-xe"
    t.device_type = "cisco_ios"
    t.username = "admin"
    t.password = "pw"
    t.secret = ""
    t.connect_timeout = 10.0
    t.command_timeout = 30.0
    t.step_run_id = None
    t._cancellation_registry = _NullCancellationRegistry()
    return t


def test_config_set_output_not_duplicated_with_blank_lines():
    transport = _make_transport()

    commands = [
        "configure terminal",
        "vlan 75",
        "name vlan_75",
        "",
        "interface Vlan 75",
        "no shutdown",
        "",
        "end",
        "write memory",
    ]
    session_output = (
        "configure terminal\n"
        "cml-switch02(config)#vlan 75\n"
        "cml-switch02(config-vlan)#name vlan_75\n"
        "cml-switch02(config-if)#no shutdown\n"
        "cml-switch02(config-if)#end\ncml-switch02#"
    )

    connection = MagicMock()
    connection.send_config_set.return_value = session_output
    connection.find_prompt.return_value = "cml-switch02#"
    connection.send_command.return_value = "Building configuration...\n[OK]"

    with (
        patch.object(
            hegemony_transport_netmiko.transport, "ConnectHandler", return_value=connection
        ),
        patch.object(hegemony_transport_netmiko.transport, "_safe_disconnect"),
    ):
        results = transport._execute_commands_sync(commands)

    assert connection.send_config_set.call_count == 1
    outputs_with_session = [r for r in results if session_output in (r.output or "")]
    assert len(outputs_with_session) == 1
    assert connection.send_command.call_count == 1
    write_results = [r for r in results if r.command == "write memory"]
    assert len(write_results) == 1
    assert "Building configuration" in (write_results[0].output or "")


def test_config_set_cli_error_skips_post_commands():
    transport = _make_transport()
    commands = ["configure terminal", "vlan 75", "end", "write memory"]
    session_output = (
        "configure terminal\n"
        "router(config)#vlan 75\n"
        "% Invalid input detected at '^' marker.\n"
        "router(config)#end\nrouter#"
    )
    connection = MagicMock()
    connection.send_config_set.return_value = session_output
    connection.find_prompt.return_value = "router#"

    with (
        patch.object(
            hegemony_transport_netmiko.transport, "ConnectHandler", return_value=connection
        ),
        patch.object(hegemony_transport_netmiko.transport, "_safe_disconnect"),
    ):
        results = transport._execute_commands_sync(commands)

    assert connection.send_command.call_count == 0
    assert all(r.command != "write memory" for r in results)
    assert any(r.command == "vlan 75" and r.exit_code == 1 for r in results)
    assert any((r.error or "") == "% Invalid input detected at '^' marker." for r in results)


def test_config_set_exception_skips_post_commands():
    transport = _make_transport()
    commands = ["configure terminal", "hostname branch-router", "end", "write memory"]
    connection = MagicMock()
    connection.send_config_set.side_effect = RuntimeError("config exploded")
    connection.find_prompt.return_value = "router#"

    with (
        patch.object(
            hegemony_transport_netmiko.transport, "ConnectHandler", return_value=connection
        ),
        patch.object(hegemony_transport_netmiko.transport, "_safe_disconnect"),
    ):
        results = transport._execute_commands_sync(commands)

    assert connection.send_command.call_count == 0
    assert all(r.command != "write memory" for r in results)
    assert any(r.command == "hostname branch-router" and r.exit_code == -1 for r in results)
    assert any((r.error or "") == "config exploded" for r in results)

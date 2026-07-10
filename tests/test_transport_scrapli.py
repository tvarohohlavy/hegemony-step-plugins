# SPDX-FileCopyrightText: 2025-2026 Jakub Trávník <jakub.travnik@gmail.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for the scrapli device transport wheel.

Covers registration under hegemony.device_transports, spec-based construction
and platform mapping, show/config execution paths (per-response result
mapping, post-command skip on config failure), timing-mode prompt answering,
and the explicit NotImplementedError staging seam.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from scrapli.exceptions import ScrapliAuthenticationFailed, ScrapliTimeout

import hegemony_transport_scrapli
from hegemony_step_sdk import DeviceConnectionSpec
from hegemony_transport_scrapli.transport import (
    ScrapliTransport,
    _NullCancellationRegistry,
)


def test_register_registers_the_scrapli_transport():
    registered: list[type] = []

    class _Registry:
        def register_transport(self, transport_class: type) -> None:
            registered.append(transport_class)

    hegemony_transport_scrapli.register(_Registry())
    assert registered == [ScrapliTransport]
    assert ScrapliTransport.transport_id == "scrapli"


def test_construct_from_spec_maps_platform():
    spec = DeviceConnectionSpec(
        host="10.0.0.1",
        port=2022,
        username="admin",
        password="pw",
        enable_secret="en",
        platform="ios-xr",
    )
    t = ScrapliTransport(spec)
    assert t.host == "10.0.0.1"
    assert t.port == 2022
    assert t.username == "admin"
    assert t.scrapli_platform == "cisco_iosxr"
    assert isinstance(t._cancellation_registry, _NullCancellationRegistry)
    # auth_secondary only present when an enable secret is set
    params = t._get_connection_params()
    assert params["auth_secondary"] == "en"
    assert params["transport"] == "paramiko"


def test_construct_unknown_platform_defaults_to_iosxe():
    spec = DeviceConnectionSpec(host="10.0.0.1", username="admin", platform="weirdos")
    assert ScrapliTransport(spec).scrapli_platform == "cisco_iosxe"


def test_construct_requires_username():
    spec = DeviceConnectionSpec(host="10.0.0.1", username="")
    with pytest.raises(ValueError, match="username"):
        ScrapliTransport(spec)


def _make_transport() -> ScrapliTransport:
    """Build a ScrapliTransport without running the validating __init__."""
    t = ScrapliTransport.__new__(ScrapliTransport)
    t.host = "10.0.0.1"
    t.port = 22
    t.platform = "ios-xe"
    t.scrapli_platform = "cisco_iosxe"
    t.username = "admin"
    t.password = "pw"
    t.secret = ""
    t.connect_timeout = 10.0
    t.command_timeout = 30.0
    t.step_run_id = None
    t._cancellation_registry = _NullCancellationRegistry()
    return t


def _response(result: str = "", failed: bool = False, elapsed: float = 0.01) -> MagicMock:
    response = MagicMock()
    response.result = result
    response.failed = failed
    response.elapsed_time = elapsed
    return response


def test_show_commands_map_to_per_command_results():
    transport = _make_transport()
    connection = MagicMock()
    connection.send_command.side_effect = [
        _response("Cisco IOS XE"),
        _response("% Invalid input detected at '^' marker.", failed=True),
    ]

    with patch.object(hegemony_transport_scrapli.transport, "Scrapli", return_value=connection):
        results = transport._execute_commands_sync(["show version", "show bork", ""])

    assert connection.open.call_count == 1
    assert [r.exit_code for r in results] == [0, 1]
    assert results[0].output == "Cisco IOS XE"
    assert results[1].error == "% Invalid input detected at '^' marker."
    # Blank commands are skipped, not sent
    assert connection.send_command.call_count == 2


def test_config_set_strips_framing_and_runs_post_commands():
    transport = _make_transport()
    connection = MagicMock()
    connection.send_configs.return_value = [_response("ok1"), _response("ok2")]
    connection.send_command.return_value = _response("Building configuration...\n[OK]")

    commands = ["configure terminal", "vlan 75", "name vlan_75", "end", "write memory"]
    with patch.object(hegemony_transport_scrapli.transport, "Scrapli", return_value=connection):
        results = transport._execute_commands_sync(commands)

    connection.send_configs.assert_called_once_with(
        ["vlan 75", "name vlan_75"], stop_on_failed=True
    )
    assert connection.send_command.call_count == 1
    write_results = [r for r in results if r.command == "write memory"]
    assert len(write_results) == 1 and write_results[0].exit_code == 0
    assert all(r.command not in ("configure terminal", "end") for r in results)


def test_config_failure_skips_post_and_marks_unattempted():
    transport = _make_transport()
    connection = MagicMock()
    # stop_on_failed truncates the responses after the failure
    connection.send_configs.return_value = [
        _response("ok"),
        _response("% Invalid input detected at '^' marker.", failed=True),
    ]

    commands = ["configure terminal", "vlan 75", "bork", "name x", "end", "write memory"]
    with patch.object(hegemony_transport_scrapli.transport, "Scrapli", return_value=connection):
        results = transport._execute_commands_sync(commands)

    assert connection.send_command.call_count == 0
    assert all(r.command != "write memory" for r in results)
    assert any(r.command == "bork" and r.exit_code == 1 for r in results)
    skipped = [r for r in results if r.command == "name x"]
    assert len(skipped) == 1 and skipped[0].exit_code == -1
    assert "Skipped" in (skipped[0].error or "")


def test_auth_failure_fills_all_results():
    transport = _make_transport()
    connection = MagicMock()
    connection.open.side_effect = ScrapliAuthenticationFailed("bad creds")

    with patch.object(hegemony_transport_scrapli.transport, "Scrapli", return_value=connection):
        results = transport._execute_commands_sync(["show version", "show ip int brief"])

    assert len(results) == 2
    assert all(r.exit_code == -1 for r in results)
    assert all("Authentication failed" in (r.error or "") for r in results)


def test_timing_mode_answers_prompts_and_finds_pattern():
    transport = _make_transport()
    connection = MagicMock()
    connection.channel.read.side_effect = [
        b"Proceed? [confirm]",
        ScrapliTimeout("no data"),
        b"Done: 1234 bytes copied in 1.0 secs",
    ]

    with patch.object(hegemony_transport_scrapli.transport, "Scrapli", return_value=connection):
        result = transport._execute_command_timing_sync(
            "copy tftp: flash:",
            read_timeout=30.0,
            answers={"[confirm]": ""},
            wait_for_patterns=["bytes copied"],
        )

    assert result.exit_code == 0
    assert "bytes copied" in result.output
    written = [call.args[0] for call in connection.channel.write.call_args_list]
    assert written[0] == "copy tftp: flash:\n"
    assert "\n" in written[1:]  # the [confirm] answer


def test_timing_mode_settles_when_channel_goes_quiet():
    transport = _make_transport()
    connection = MagicMock()
    connection.channel.read.side_effect = [
        b"Reload scheduled",
        ScrapliTimeout("q1"),
        ScrapliTimeout("q2"),
        ScrapliTimeout("q3"),
    ]

    with patch.object(hegemony_transport_scrapli.transport, "Scrapli", return_value=connection):
        result = transport._execute_command_timing_sync("reload in 5", read_timeout=30.0)

    assert result.exit_code == 0
    assert result.output == "Reload scheduled"
    # Settled after exactly three consecutive quiet reads — no further polling
    assert connection.channel.read.call_count == 4


async def test_staging_methods_are_an_explicit_seam():
    transport = _make_transport()
    with pytest.raises(NotImplementedError, match="netmiko"):
        await transport.scp_put(local_path="/tmp/x", dest_fs="flash:", dest_filename="x")
    with pytest.raises(NotImplementedError, match="netmiko"):
        await transport.http_transfer(url="https://x", dest_fs="flash:", dest_filename="x")

# SPDX-FileCopyrightText: 2025-2026 Jakub Trávník <jakub.travnik@gmail.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Registration and metadata smoke tests for the core handlers wheel.

Deep behavioral coverage for these handlers lives in the platform repo (which
exercises them through the installed wheel with host-bound services); this
suite pins what the wheel itself owns: the handler set, ids, metadata, and
config schemas.
"""

import json
from typing import Any

import hegemony_step_handlers_core as core
from hegemony_step_sdk import BaseHandler, StepKind

EXPECTED_IDS = {
    "actions.execute_cli",
    "actions.run_container",
    "actions.run_flow",
    "actions.sleep",
    "checks.assert",
    "checks.collect_evidence",
    "checks.compare_evidence",
    "checks.connectivity",
    "checks.poll_until",
    "checks.wait_reachable_stable",
    "hegemony.git.sync_repo",
    "noop",
    "notifications.send",
    "upgrade.cleanup",
    "upgrade.install",
    "upgrade.preflight",
    "upgrade.stage",
    "upgrade.verify",
}


class RecordingRegistry:
    api_version = 1

    def __init__(self) -> None:
        # list[Any]: the protocol's parameter type is plain ``type`` (duck-typed).
        self.registered: list[Any] = []

    def register_handler_type(self, handler_class: type) -> None:
        self.registered.append(handler_class)


def test_register_registers_all_handlers():
    registry = RecordingRegistry()
    core.register(registry)
    ids = {cls.handler_id for cls in registry.registered}
    assert ids == EXPECTED_IDS
    assert len(registry.registered) == len(EXPECTED_IDS)


def test_all_handlers_are_base_handler_subclasses():
    for cls in core.ALL_HANDLERS:
        assert issubclass(cls, BaseHandler), cls
        assert cls.handler_id, cls
        assert cls.supported_kinds, cls
        assert all(isinstance(kind, StepKind) for kind in cls.supported_kinds), cls


def test_all_handlers_declare_config_models_with_json_schemas():
    for cls in core.ALL_HANDLERS:
        model = cls.config_model
        assert model is not None, cls.handler_id
        json.dumps(model.model_json_schema())


def test_visible_handlers_have_editor_metadata():
    hidden = {cls.handler_id for cls in core.ALL_HANDLERS if cls.hidden}
    assert hidden == {"noop", "hegemony.git.sync_repo"}
    for cls in core.ALL_HANDLERS:
        if cls.hidden:
            continue
        assert cls.display_name and cls.display_name != cls.handler_id, cls.handler_id
        assert cls.description, cls.handler_id
        assert cls.category, cls.handler_id


async def test_connectivity_probe_rejects_unknown_type():
    from hegemony_step_handlers_core.connectivity_check import ConnectivityCheckHandler
    from hegemony_step_sdk import HandlerContext

    handler = ConnectivityCheckHandler()
    ctx = HandlerContext(
        run_id="r",
        flow_id="f",
        step_run_id="sr",
        step_id="s",
        phase="VERIFY",
        kind="CHECK",
        config={"check_type": "bogus"},
        target_roles=["primary"],
        target_devices_by_role={"primary": [{"id": "d1", "name": "r1", "mgmt_host": "192.0.2.1"}]},
    )
    result = await handler.execute(ctx)
    assert result.success is False
    assert "Invalid check_type" in (result.error or "")


async def test_connectivity_tcp_probe_connection_refused():
    from hegemony_step_handlers_core.connectivity_check import _tcp_connect_probe

    # RFC 5737 TEST-NET address with an unroutable port would hang; use localhost
    # with a port that is almost certainly closed for a fast refusal.
    result = await _tcp_connect_probe("127.0.0.1", {"port": 1, "timeout_ms": 2000})
    assert result.ok is False
    assert result.error_kind in {"connection_refused", "timeout", "network_error"}

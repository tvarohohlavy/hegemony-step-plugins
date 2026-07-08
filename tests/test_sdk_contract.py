# SPDX-FileCopyrightText: 2025-2026 Jakub Trávník <jakub.travnik@gmail.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SDK contract surface tests.

Pins the public API plugin authors rely on; the host keeps a mirror parity
test so the duck-typed platform registry and this SDK stay in lock-step.
"""

import inspect

import hegemony_step_sdk as sdk


def test_public_surface():
    for name in (
        "BaseHandler",
        "CommandResult",
        "ContainerRuntime",
        "HandlerContext",
        "HandlerResult",
        "HandlerServices",
        "HandlerTargeting",
        "StepHandlerRegistry",
        "StepKind",
        "Transport",
        "ShellResult",
        "ShellTransport",
        "BaseProbe",
        "ProbeResult",
        "ProbeRegistry",
        "MAX_CHAIN_OUTPUT_CHARS",
        "DEFAULT_DEVICE_PLATFORM",
        "SDK_ABI_VERSION",
        "STEP_HANDLER_ENTRY_POINT_GROUP",
        "PROBE_ENTRY_POINT_GROUP",
        "resolve_target_devices_for_roles",
    ):
        assert hasattr(sdk, name), name


def test_entry_point_group_and_abi():
    assert sdk.STEP_HANDLER_ENTRY_POINT_GROUP == "hegemony.step_handlers"
    assert sdk.PROBE_ENTRY_POINT_GROUP == "hegemony.probes"
    assert sdk.SDK_ABI_VERSION == 1


def test_handler_services_declares_run_probe():
    assert list(inspect.signature(sdk.HandlerServices.run_probe).parameters) == [
        "self",
        "check_type",
        "address",
        "options",
    ]


def test_probe_registry_protocol_shape():
    assert list(inspect.signature(sdk.ProbeRegistry.register_probe).parameters) == [
        "self",
        "probe_class",
    ]


def test_step_kind_values():
    assert {kind.value for kind in sdk.StepKind} == {
        "CHECK",
        "ACTION",
        "WAIT",
        "TRANSFER",
        "EXECUTE",
    }
    # str-enum: values compare equal to plain strings across enum copies
    assert sdk.StepKind.CHECK == "CHECK"


def test_handler_context_binds_services():
    ctx = sdk.HandlerContext(
        run_id="r",
        flow_id="f",
        step_run_id="sr",
        step_id="s",
        phase="EXECUTE",
        kind="ACTION",
    )
    try:
        ctx.require_services()
    except RuntimeError as exc:
        assert "services" in str(exc)
    else:
        raise AssertionError("require_services must fail when unbound")


def test_registry_protocol_shape():
    signature = inspect.signature(sdk.StepHandlerRegistry.register_handler_type)
    assert list(signature.parameters) == ["self", "handler_class"]


def test_base_handler_validates_with_config_model():
    from pydantic import BaseModel

    class Config(BaseModel):
        name: str

    class Handler(sdk.BaseHandler):
        handler_id = "test.handler"
        supported_kinds = [sdk.StepKind.ACTION]
        config_model = Config

        async def execute(self, ctx):  # pragma: no cover - not executed
            return sdk.HandlerResult(success=True)

    handler = Handler()
    assert handler.validate_config({"name": "x"}) == []
    errors = handler.validate_config({})
    assert errors and errors[0].startswith("name:")

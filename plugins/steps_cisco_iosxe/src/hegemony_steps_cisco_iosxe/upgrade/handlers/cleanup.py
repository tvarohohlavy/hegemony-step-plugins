# SPDX-FileCopyrightText: 2025-2026 Jakub Trávník <jakub.travnik@gmail.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Upgrade Cleanup Handler.

Removes inactive packages/old images after successful upgrade.

This handler should run in CLEANUP phase after verification.
"""

import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from hegemony_step_sdk import (
    DEFAULT_DEVICE_PLATFORM,
    BaseHandler,
    HandlerContext,
    HandlerResult,
    HandlerTargeting,
    StepKind,
)

from ..driver import UpgradeMode, get_driver

logger = logging.getLogger(__name__)


class UpgradeCleanupConfig(BaseModel):
    """Config for ``cisco.iosxe.upgrade.cleanup``."""

    model_config = ConfigDict(extra="allow")

    upgrade_mode: Literal["install", "bundle"] = Field(
        default="install",
        title="Upgrade Mode",
        json_schema_extra={
            "x_option_labels": {
                "install": "Install Mode (modern IOS-XE)",
                "bundle": "Bundle Mode (legacy ISR)",
            }
        },
    )
    remove_inactive: bool = Field(
        default=True,
        title="Remove inactive packages/old images",
        description='For install mode: runs "install remove inactive"',
    )
    keep_versions: int = Field(
        default=1,
        ge=0,
        le=5,
        title="Versions to Keep",
        description="Number of old versions to keep (for bundle mode)",
        json_schema_extra={"x_show_when": {"field": "upgrade_mode", "value": "bundle"}},
    )


class UpgradeCleanupHandler(BaseHandler):
    """Handler for post-upgrade cleanup.

    For install-mode:
        Runs 'install remove inactive' to remove old packages

    For bundle-mode:
        Deletes old .bin images from flash

    Required params:
        platform: Device platform (e.g., "ios-xe")

    Optional params:
        upgrade_mode: "install" or "bundle" (default: "install")
        remove_inactive: Whether to remove old packages (default: true)
        keep_versions: Number of old versions to keep (default: 1)

    Output context:
        cleanup.removed_packages: List of removed packages/files
    """

    handler_id = "cisco.iosxe.upgrade.cleanup"
    default_timeout_seconds = 7200
    supported_kinds = [StepKind.ACTION]
    display_name = "Upgrade: Cleanup"
    description = "Remove inactive packages/old images after a successful upgrade."
    category = "Upgrade"
    targeting = HandlerTargeting(roles=True, ips=False)
    config_model = UpgradeCleanupConfig
    default_config = {"upgrade_mode": "install", "remove_inactive": True, "keep_versions": 1}

    async def execute(self, ctx: HandlerContext) -> HandlerResult:
        """Run cleanup on all target devices."""
        target_devices = ctx.get_target_devices()
        if not target_devices:
            return HandlerResult(
                success=False,
                error="No target devices configured",
                summary="Missing target device",
            )

        # Get parameters
        platform = ctx.config.get("platform", DEFAULT_DEVICE_PLATFORM)
        mode_str = ctx.config.get("upgrade_mode", "install")
        upgrade_mode = UpgradeMode.BUNDLE if mode_str.lower() == "bundle" else UpgradeMode.INSTALL

        remove_inactive = ctx.config.get("remove_inactive", True)
        keep_versions = ctx.config.get("keep_versions", 1)

        if not remove_inactive:
            return HandlerResult(
                success=True,
                summary="Cleanup skipped (remove_inactive=false)",
                evidence=[],
            )

        # Get driver for platform
        try:
            driver = get_driver(platform, upgrade_mode)
        except ValueError as e:
            return HandlerResult(
                success=False,
                error=str(e),
                summary=f"Unsupported platform: {platform}",
            )

        all_evidence = []
        success_count = 0
        failure_count = 0
        failed_devices = []
        total_removed = []
        output_context = {}

        services = ctx.require_services()
        for device in target_devices:
            device_id = device.get("id", "unknown")
            device_name = device.get("name", device_id)
            host = device.get("mgmt_host")
            if not host:
                logger.error(f"Cleanup skipped for {device_name}: missing mgmt_host")
                failure_count += 1
                failed_devices.append(device_name)
                all_evidence.append(
                    {
                        "kind": "cli_output",
                        "name": f"Cleanup Error: {device_name}",
                        "device_id": device_id,
                        "content_text": "Error during cleanup:\nmissing mgmt_host",
                        "content_json": {
                            "device_id": device_id,
                            "device_name": device_name,
                            "error": "missing mgmt_host",
                            "success": False,
                        },
                    }
                )
                continue

            await ctx.emit_progress(
                f"Running cleanup on {device_name}",
                device_id,
                {"phase": "cleanup", "status": "running"},
            )

            try:
                ssh = services.connect(device, platform=platform)
                result = await driver.cleanup(
                    ssh,
                    remove_inactive=remove_inactive,
                    keep_versions=keep_versions,
                )

                if result.success:
                    success_count += 1

                    removed = result.removed_packages or []
                    if removed:
                        summary = f"Removed {len(removed)} package(s)/file(s)"
                        total_removed.extend(removed)
                    else:
                        summary = "No inactive packages to remove"

                    await ctx.emit_progress(
                        summary,
                        device_id,
                        {"phase": "cleanup", "status": "success"},
                    )
                else:
                    failure_count += 1
                    failed_devices.append(device_name)
                    await ctx.emit_progress(
                        f"Cleanup failed: {result.error}",
                        device_id,
                        {"phase": "cleanup", "status": "failed"},
                    )

                # Store output context
                device_context = {
                    "removed_packages": result.removed_packages or [],
                }
                output_context[device_id] = device_context

                # Build evidence with proper structure for artifact saving
                removed = result.removed_packages or []
                content_lines = [
                    f"Device: {device_name}",
                    f"Platform: {platform} ({mode_str} mode)",
                    f"Success: {result.success}",
                    f"Packages Removed: {len(removed)}",
                ]
                if removed:
                    content_lines.append("\nRemoved items:")
                    for pkg in removed:
                        content_lines.append(f"  - {pkg}")
                if result.error:
                    content_lines.append(f"Error: {result.error}")
                if result.cli_output:
                    content_lines.append(f"\n--- CLI Output ---\n{result.cli_output}")

                evidence_item = {
                    "kind": "cli_output",
                    "name": f"Cleanup: {device_name}",
                    "device_id": device_id,
                    "content_text": "\n".join(content_lines),
                    "content_json": {
                        "device_id": device_id,
                        "device_name": device_name,
                        "platform": platform,
                        "upgrade_mode": mode_str,
                        "success": result.success,
                        "removed_packages": result.removed_packages,
                        "error": result.error,
                    },
                }
                all_evidence.append(evidence_item)

            except Exception as e:
                logger.error(f"Cleanup failed for {device_name}: {e}")
                failure_count += 1
                failed_devices.append(device_name)

                all_evidence.append(
                    {
                        "kind": "cli_output",
                        "name": f"Cleanup Error: {device_name}",
                        "device_id": device_id,
                        "content_text": f"Error during cleanup:\n{str(e)}",
                        "content_json": {
                            "device_id": device_id,
                            "device_name": device_name,
                            "error": str(e),
                            "success": False,
                        },
                    }
                )

        # Determine overall success
        overall_success = failure_count == 0

        if overall_success:
            if total_removed:
                summary = f"Cleanup completed on {success_count} device(s), removed {len(total_removed)} item(s)"
            else:
                summary = f"Cleanup completed on {success_count} device(s)"
        else:
            summary = f"Cleanup failed on {failure_count} device(s): {', '.join(failed_devices)}"

        return HandlerResult(
            success=overall_success,
            summary=summary,
            evidence=all_evidence,
            metrics={
                "success_count": success_count,
                "failure_count": failure_count,
                "total_removed": len(total_removed),
                "output_context": output_context,
            },
            error=summary if not overall_success else None,
        )

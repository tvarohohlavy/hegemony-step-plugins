# SPDX-FileCopyrightText: 2025-2026 Jakub Trávník <jakub.travnik@gmail.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Hegemony core step handlers.

Registers the platform's built-in step handlers under the
``hegemony.step_handlers`` entry-point group: CLI execution, evidence
collection/comparison/assertions, polling, sleep, connectivity checks,
container execution, nested flows, notifications, git sync, and the IOS-XE
upgrade family. Auto-installed with the platform and versioned in lockstep
with it. Handlers reach every platform facility through ``ctx.services``.
"""

from __future__ import annotations

from hegemony_step_sdk import BaseHandler, StepHandlerRegistry

from .assert_check import AssertHandler
from .collect_evidence import CollectEvidenceHandler
from .compare_evidence import CompareEvidenceHandler
from .connectivity_check import ConnectivityCheckHandler
from .execute_cli import ExecuteCLIActionHandler
from .git_integration import GitSyncRepoHandler
from .noop import NoOpHandler
from .poll_until import PollUntilHandler
from .run_container import RunContainerHandler
from .run_flow import RunFlowHandler
from .send_notification import SendNotificationHandler
from .sleep_handler import SleepHandler
from .upgrade.handlers import (
    UpgradeCleanupHandler,
    UpgradeInstallHandler,
    UpgradePreflightHandler,
    UpgradeStageHandler,
    UpgradeVerifyHandler,
)
from .wait_reachable import WaitReachableHandler

#: Every handler class this wheel registers (order is cosmetic; ids are unique).
ALL_HANDLERS: tuple[type[BaseHandler], ...] = (
    AssertHandler,
    CollectEvidenceHandler,
    CompareEvidenceHandler,
    ConnectivityCheckHandler,
    ExecuteCLIActionHandler,
    GitSyncRepoHandler,
    NoOpHandler,
    PollUntilHandler,
    RunContainerHandler,
    RunFlowHandler,
    SendNotificationHandler,
    SleepHandler,
    UpgradeCleanupHandler,
    UpgradeInstallHandler,
    UpgradePreflightHandler,
    UpgradeStageHandler,
    UpgradeVerifyHandler,
    WaitReachableHandler,
)


def register(registry: StepHandlerRegistry) -> None:
    """Entry point: register every core handler with the host registry."""
    for handler_class in ALL_HANDLERS:
        registry.register_handler_type(handler_class)


__all__ = ["ALL_HANDLERS", "register", *sorted(cls.__name__ for cls in ALL_HANDLERS)]

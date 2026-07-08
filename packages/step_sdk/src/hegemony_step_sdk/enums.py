# SPDX-FileCopyrightText: 2025-2026 Jakub Trávník <jakub.travnik@gmail.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Step-handler enums.

These are the canonical definitions; the platform's ``packages/core/enums.py``
re-exports them so existing ``from packages.core.enums import StepKind`` imports keep
the same object identity, while out-of-tree handler wheels import them from here and
never depend on Hegemony. Mirrors the ``hegemony_inventory_sdk.enums`` pattern.
"""

from __future__ import annotations

from enum import Enum


class StepKind(str, Enum):  # noqa: UP042 - (str, Enum) keeps str() parity with platform enums
    """Behavior category for a step.

    Determines how the engine treats the step and what handlers are valid.
    """

    CHECK = "CHECK"
    ACTION = "ACTION"
    WAIT = "WAIT"
    TRANSFER = "TRANSFER"
    EXECUTE = "EXECUTE"

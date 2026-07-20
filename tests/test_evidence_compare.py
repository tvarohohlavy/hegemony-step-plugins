# SPDX-FileCopyrightText: 2025-2026 Jakub Trávník <jakub.travnik@gmail.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for evidence.compare mode + volatile-line filtering."""

from __future__ import annotations

from hegemony_steps_evidence.compare import CompareEvidenceHandler

# Two routing-table captures that are identical except for OSPF uptime timers
# (the "00:0x:yz" columns) — the kind of volatile output that always differs.
_ROUTE_PRE = """\
O    10.255.255.1/32 [110/20] via 10.0.0.1, 00:01:11, eth0
O    10.255.255.2/32 [110/20] via 10.0.0.2, 00:03:47, eth1
"""
_ROUTE_POST_TIMERS_ONLY = """\
O    10.255.255.1/32 [110/20] via 10.0.0.1, 00:09:52, eth0
O    10.255.255.2/32 [110/20] via 10.0.0.2, 00:12:03, eth1
"""
# Same as _ROUTE_PRE but with the announced /32 added (the meaningful change),
# plus the same drifting timers.
_ROUTE_POST_REAL_CHANGE = """\
O    10.255.255.1/32 [110/20] via 10.0.0.1, 00:09:52, eth0
O    10.255.255.2/32 [110/20] via 10.0.0.2, 00:12:03, eth1
O    10.200.150.1/32 [110/20] via 10.0.0.1, 00:00:04, eth0
"""
# Regex that drops the volatile uptime column so only routes are compared.
_TIMER_PATTERN = r", \d\d:\d\d:\d\d,"


def _handler() -> CompareEvidenceHandler:
    return CompareEvidenceHandler()


def test_exact_mode_fails_on_diff_passes_on_match() -> None:
    handler = _handler()
    passed, _ = handler._compare("a\nb", "a\nb", "exact", [])
    assert passed is True
    passed, _ = handler._compare("a\nb", "a\nc", "exact", [])
    assert passed is False


def test_changed_mode_inverts_exact() -> None:
    """'changed' passes on a difference and fails when nothing changed."""
    handler = _handler()
    passed, _ = handler._compare("a\nb", "a\nc", "changed", [])
    assert passed is True
    passed, _ = handler._compare("a\nb", "a\nb", "changed", [])
    assert passed is False


def test_ignore_patterns_strip_volatile_timers() -> None:
    """Captures differing only by timers compare equal once timers are ignored."""
    handler = _handler()
    # Without ignoring, the drifting timers always look like a change.
    passed, _ = handler._compare(_ROUTE_PRE, _ROUTE_POST_TIMERS_ONLY, "exact", [])
    assert passed is False
    # Ignoring the timer column, the two are identical → exact passes,
    # and 'changed' correctly reports no meaningful change.
    passed, _ = handler._compare(_ROUTE_PRE, _ROUTE_POST_TIMERS_ONLY, "exact", [], [_TIMER_PATTERN])
    assert passed is True
    passed, _ = handler._compare(
        _ROUTE_PRE, _ROUTE_POST_TIMERS_ONLY, "changed", [], [_TIMER_PATTERN]
    )
    assert passed is False


def test_ignore_patterns_keep_real_change() -> None:
    """A genuine change (a new prefix) still registers once timers are ignored."""
    handler = _handler()
    passed, _ = handler._compare(
        _ROUTE_PRE, _ROUTE_POST_REAL_CHANGE, "changed", [], [_TIMER_PATTERN]
    )
    assert passed is True
    passed, _ = handler._compare(_ROUTE_PRE, _ROUTE_POST_REAL_CHANGE, "exact", [], [_TIMER_PATTERN])
    assert passed is False


def test_mask_ignored_removes_matches_and_tolerates_bad_regex() -> None:
    handler = _handler()
    text = "keep me\nBytes: 123\nkeep me too"
    masked = handler._mask_ignored(text, [r"Bytes: \d+"])
    assert "Bytes:" not in masked
    assert "keep me" in masked and "keep me too" in masked
    # An invalid regex is skipped, not raised — the other pattern still applies.
    masked = handler._mask_ignored(text, ["(", r"Bytes: \d+"])
    assert "Bytes:" not in masked

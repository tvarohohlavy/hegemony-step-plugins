<!--
SPDX-FileCopyrightText: 2025-2026 Jakub Trávník <jakub.travnik@gmail.com>

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# hegemony-step-handlers-core

The core step-handler set for Hegemony, auto-installed with the platform and
versioned in lockstep with it.

Registers under the `hegemony.step_handlers` entry-point group:

| Handler | Purpose |
| --- | --- |
| `actions.execute_cli` | Run CLI commands on target devices |
| `actions.run_container` | Run a command inside a Docker container |
| `actions.run_flow` | Launch another committed flow as a child run |
| `actions.sleep` | Pause the flow for a fixed duration |
| `checks.assert` | Assert an expected value against collected evidence |
| `checks.collect_evidence` | Capture CLI outputs as evidence |
| `checks.compare_evidence` | Diff evidence between two steps |
| `checks.connectivity` | One-shot connectivity probes (self-contained tcp/icmp) |
| `checks.poll_until` | Poll a device command until output matches |
| `checks.wait_reachable_stable` | Wait for stable reachability |
| `notifications.send` | Send an on-demand notification |
| `hegemony.git.sync_repo` | Internal: repo-wide flow git sync |
| `noop` | Internal: placeholder/testing step |
| `upgrade.preflight` / `.stage` / `.install` / `.verify` / `.cleanup` | IOS-XE upgrade workflow (install + bundle modes) |

Handlers reach every platform facility — device transports, secret/template
resolution, the internal API, notifications — through `ctx.services`
(`hegemony_step_sdk.HandlerServices`); this package never imports Hegemony
internals.

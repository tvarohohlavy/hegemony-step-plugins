<!--
SPDX-FileCopyrightText: 2025-2026 Jakub Trávník <jakub.travnik@gmail.com>

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Hegemony Step Plugins

Step-handler SDK and plugin wheels for [Hegemony](https://github.com/tvarohohlavy/Hegemony).

Step handlers implement the work one flow step performs (run CLI commands on
devices, launch a container, stage an upgrade image, …). Handler types are
pluggable: wheels register handler classes under the `hegemony.step_handlers`
entry-point group and the platform discovers them at startup.

## Packages

- `packages/step_sdk` — `hegemony-step-sdk`: the public, dependency-light
  (pydantic only) SDK. Defines the handler contract (`BaseHandler`,
  `HandlerContext`, `HandlerResult`), the injected services ABI
  (`HandlerServices`, `Transport`), canonical enums (`StepKind`), and the
  registration protocol.
- Handler wheels, one namespace prefix each (see `CONVENTIONS.md` for the
  naming/grouping rules — the entry-point name is the claimed prefix):

  | Wheel | Namespace | Handlers |
  | --- | --- | --- |
  | `plugins/steps_general` | `general.` | noop (hidden), sleep |
  | `plugins/steps_probe` | `probe.` | connectivity, wait_reachable |
  | `plugins/steps_netcli` | `netcli.` | execute, collect_evidence, poll_until |
  | `plugins/steps_evidence` | `evidence.` | assert, compare |
  | `plugins/steps_container` | `container.` | run |
  | `plugins/steps_flow` | `flow.` | run, notify, git_sync (hidden) |
  | `plugins/steps_cisco_iosxe` | `cisco.iosxe.` | upgrade.preflight/stage/install/verify/cleanup |

All wheels are auto-installed with the platform and versioned in lockstep
with it, except that hardened deployments may omit `hegemony-steps-container`
to disable container execution entirely.

## Development

```bash
task setup   # install workspace + pre-commit hooks
task ci      # lint, typecheck, REUSE, tests, build wheels, smoke-install
```

Handlers reach every platform facility (device transports, secret/template
resolution, the internal API) through `ctx.services` — plugin code never
imports Hegemony internals.

See `CONTRIBUTING.md` and `LICENSING.md` for contribution and licensing terms.

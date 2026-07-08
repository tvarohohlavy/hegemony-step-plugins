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
  (pydantic + httpx types only) SDK. Defines the handler contract
  (`BaseHandler`, `HandlerContext`, `HandlerResult`), the injected services
  ABI (`HandlerServices`, `Transport`), canonical enums (`StepKind`), and the
  registration protocol.
- `plugins/step_handlers_core` — `hegemony-step-handlers-core`: the core
  handler set (CLI execution, evidence collection/comparison/assertions,
  polling, sleep, connectivity checks, container execution, nested flows,
  notifications, git sync, and the IOS-XE upgrade family). Auto-installed
  with the platform; versioned in lockstep with it.

## Development

```bash
task setup   # install workspace + pre-commit hooks
task ci      # lint, typecheck, REUSE, tests, build wheels, smoke-install
```

Handlers reach every platform facility (device transports, secret/template
resolution, the internal API) through `ctx.services` — plugin code never
imports Hegemony internals.

See `CONTRIBUTING.md` and `LICENSING.md` for contribution and licensing terms.

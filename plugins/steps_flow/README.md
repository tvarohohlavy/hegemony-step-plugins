<!--
SPDX-FileCopyrightText: 2025-2026 Jakub Trávník <jakub.travnik@gmail.com>

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# hegemony-steps-flow

Platform-orchestration steps: launch nested flow runs, send on-demand
notifications, trigger git flow-definition syncs.

Handlers: `flow.run`, `flow.notify`, `flow.git_sync` (hidden).

Namespace prefix (= entry-point name): `flow.` — see the repo-level
`CONVENTIONS.md` for the naming rules.

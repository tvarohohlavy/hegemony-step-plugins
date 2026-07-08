<!--
SPDX-FileCopyrightText: 2025-2026 Jakub Trávník <jakub.travnik@gmail.com>

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# hegemony-steps-netcli

Network-device CLI paradigm: execute command lines, collect outputs as
evidence, poll until output matches. Vendor-neutral by design — platform
dialects and transports (netmiko/scrapli, ssh) are resolved beneath the
handler layer from device access config.

Handlers: `netcli.execute`, `netcli.collect_evidence`, `netcli.poll_until`.

Namespace prefix (= entry-point name): `netcli.` — see the repo-level
`CONVENTIONS.md` for the naming rules.

# SPDX-FileCopyrightText: 2025-2026 Jakub Trávník <jakub.travnik@gmail.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Install built wheels in a clean virtualenv and verify imports/entry points."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

from package_paths import ROOT

EXPECTED_MODULES = (
    "hegemony_step_sdk",
    "hegemony_steps_general",
    "hegemony_steps_probe",
    "hegemony_steps_netcli",
    "hegemony_steps_evidence",
    "hegemony_steps_container",
    "hegemony_steps_flow",
    "hegemony_steps_cisco_iosxe",
    "hegemony_steps_shell",
    "hegemony_steps_monitor",
    "hegemony_probe_net",
    "hegemony_transport_netmiko",
)

# Entry-point names under hegemony.step_handlers (claimed handler-id namespaces).
EXPECTED_ENTRY_POINTS = {
    "general",
    "probe",
    "netcli",
    "evidence",
    "container",
    "flow",
    "cisco.iosxe",
    "monitor",
}

# Entry-point names under hegemony.probes (probe wheels).
EXPECTED_PROBE_ENTRY_POINTS = {
    "net",
}

# Entry-point names under hegemony.device_transports (transport wheels).
EXPECTED_TRANSPORT_ENTRY_POINTS = {
    "netmiko",
}


def _python_bin(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / "python"


def main() -> None:
    wheels = sorted((ROOT / "dist").glob("*.whl"))
    if len(wheels) != 12:
        raise SystemExit(f"Expected 12 wheels in dist/, found {len(wheels)}")

    tmp = Path(tempfile.mkdtemp(prefix="hegemony-step-wheel-smoke-"))
    try:
        venv_dir = tmp / "venv"
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        python = _python_bin(venv_dir)
        subprocess.run(
            ["uv", "pip", "install", "--python", str(python), *map(str, wheels)],
            cwd=ROOT,
            check=True,
        )
        code = f"""
from importlib import import_module
from importlib.metadata import entry_points

modules = {EXPECTED_MODULES!r}
for module in modules:
    import_module(module)

entries = entry_points(group="hegemony.step_handlers")
names = {{entry.name for entry in entries}}
expected = {EXPECTED_ENTRY_POINTS!r}
missing = expected - names
assert not missing, missing

probe_entries = entry_points(group="hegemony.probes")
probe_names = {{entry.name for entry in probe_entries}}
probe_expected = {EXPECTED_PROBE_ENTRY_POINTS!r}
probe_missing = probe_expected - probe_names
assert not probe_missing, probe_missing

transport_entries = entry_points(group="hegemony.device_transports")
transport_names = {{entry.name for entry in transport_entries}}
transport_expected = {EXPECTED_TRANSPORT_ENTRY_POINTS!r}
transport_missing = transport_expected - transport_names
assert not transport_missing, transport_missing
"""
        subprocess.run([str(python), "-c", code], check=True)
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()

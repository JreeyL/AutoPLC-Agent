"""OpenPLC v3 runtime integration for ST compile + simulation checks (E3S1T8).

Discovers a local OpenPLC v3 installation, compiles a Structured Text file with
the OpenPLC toolchain (``webserver/scripts/compile_program.sh``), and runs the
resulting ``webserver/core/openplc`` runtime for a few scan cycles to confirm it
executes without segmentation faults or runtime panics.

Compatibility handling:
- OpenPLC's ``iec2c`` does not accept ``//`` line comments, so they are stripped
  before compiling (consistent with the MATIEC wrapper).
- A standalone ``PROGRAM`` block is wrapped in a minimal
  ``CONFIGURATION``/``RESOURCE``/``TASK`` so OpenPLC can instanciate it.
- Computing changes the OpenPLC webserver state (``core/`` outputs and
  ``active_program``), so the original state is backed up and restored after
  each run.

No business-logic semantic evaluation is performed; only compile and
crash-free execution are checked.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# Candidate OpenPLC v3 install root directories.
_ROOT_CANDIDATES = (
    Path(os.environ.get("OPENPLC_ROOT", "")),
    Path(os.environ.get("HOME", "/home")) / "OpenPLC_v3",
    Path(os.environ.get("HOME", "/home")) / "OpenPLC_v2",
)


@dataclass
class SimulationResult:
    """Outcome of an OpenPLC compile + simulation run."""

    compiled: bool
    compile_returncode: int = -1
    ran_stably: bool = False
    returncode: int = -1
    stdout: str = ""
    stderr: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def first_error(self) -> str:
        return self.errors[0] if self.errors else ""


def _find_openplc_root() -> Path | None:
    """Locate an OpenPLC install with a usable runtime and compile script."""
    for cand in _ROOT_CANDIDATES:
        if not cand:
            continue
        if (
            (cand / "webserver" / "core" / "openplc").exists()
            and (cand / "webserver" / "scripts" / "compile_program.sh").exists()
        ):
            return cand
    return None


def is_openplc_available() -> bool:
    """Return True if a usable OpenPLC v3 installation is found."""
    return _find_openplc_root() is not None


def _strip_line_comments(code: str) -> str:
    return re.sub(r"//.*$", "", code, flags=re.M)


def _program_name(code: str) -> str | None:
    m = re.search(r"^\s*PROGRAM\s+([A-Za-z_]\w*)", code, flags=re.M)
    return m.group(1) if m else None


def _configuration_wrapper(program_name: str) -> str:
    """Minimal IEC 61131-3 CONFIGURATION/RESOURCE/TASK around a PROGRAM."""
    return (
        "\n"
        "CONFIGURATION Config0\n"
        "    RESOURCE Res0 ON PLC\n"
        "        TASK task0(INTERVAL := T#20ms, PRIORITY := 0);\n"
        f"        PROGRAM inst0 WITH task0 : {program_name};\n"
        "    END_RESOURCE\n"
        "END_CONFIGURATION\n"
    )


def run_openplc_simulation(
    st_path: Path | str, run_seconds: float = 1.0
) -> SimulationResult:
    """Compile ``st_path`` with OpenPLC and run the runtime for ``run_seconds``.

    Returns a :class:`SimulationResult`. ``ran_stably`` is True when the runtime
    completes ``run_seconds`` of scan cycles without a crash (the ``timeout``
    wrapper reports exit code 124 for a process killed after running its full
    duration). Temporary compile dirs and OpenPLC webserver state are restored
    afterwards.
    """
    root = _find_openplc_root()
    if root is None:
        raise RuntimeError("OpenPLC v3 installation not found")
    ws = root / "webserver"

    backup = Path(tempfile.mkdtemp(prefix="openplc_sim_"))
    try:
        # Back up the compile outputs and active program so we can restore.
        shutil.copytree(ws / "core", backup / "core")
        shutil.copy(ws / "active_program", backup / "active_program")

        code = Path(st_path).read_text(encoding="utf-8")
        code = _strip_line_comments(code)
        program_name = _program_name(code)
        if program_name is None:
            return SimulationResult(
                compiled=False, errors=["could not find a PROGRAM block"]
            )
        code = code + _configuration_wrapper(program_name)

        st_name = "gen_sim.st"
        (ws / "st_files" / st_name).write_text(code, encoding="utf-8")

        proc = subprocess.run(
            ["bash", "scripts/compile_program.sh", st_name],
            cwd=ws,
            capture_output=True,
            text=True,
            timeout=180,
        )
        combined = proc.stdout + proc.stderr
        if proc.returncode != 0:
            return SimulationResult(
                compiled=False,
                compile_returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                errors=[ln.strip() for ln in combined.splitlines() if "error" in ln.lower()],
            )

        run = subprocess.run(
            ["timeout", f"{run_seconds:g}", "./openplc"],
            cwd=ws / "core",
            capture_output=True,
            text=True,
            timeout=run_seconds + 15,
        )
        # 124: killed by timeout after running its full duration (stable).
        ran_stably = run.returncode == 124
        return SimulationResult(
            compiled=True,
            compile_returncode=0,
            ran_stably=ran_stably,
            returncode=run.returncode,
            stdout=run.stdout,
            stderr=run.stderr,
        )
    finally:
        if (backup / "core").exists():
            shutil.rmtree(ws / "core")
            shutil.copytree(backup / "core", ws / "core")
        shutil.copy(backup / "active_program", ws / "active_program")
        (ws / "st_files" / "gen_sim.st").unlink(missing_ok=True)
        shutil.rmtree(backup, ignore_errors=True)

"""MATIEC compiler wrapper for IEC 61131-3 ST syntax / compile checking (E3S1T7).

Locates the ``iec2c`` binary (built from the MATIEC toolchain), discovers the
MATIEC standard library (containing ``ieclib.txt``), and compiles a structured
text (ST) file, returning a structured :class:`CompilationResult`.

Known MATIEC compatibility notes:
- ``iec2c`` reads its standard library from a ``lib/`` directory relative to the
  compile working directory; the wrapper copies the discovered library next to
  the generated sources.
- MATIEC does not accept ``//`` line comments (IEC 61131-3 uses ``(* *)``). The
  generated ST outputs use ``//`` comments, so the wrapper strips them before
  compiling. This is a formatting normalization only; program logic is
  unchanged.
- A standalone ``PROGRAM`` block compiles without an enclosing
  ``CONFIGURATION``, but the wrapper can optionally synthesize a minimal
  ``CONFIGURATION`` / ``RESOURCE`` / ``TASK`` wrapper for POU containment when
  requested.

This module performs no business-logic semantic evaluation; it only checks
syntax / compilation validity.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# Default candidate locations for the MATIEC standard library (containing ieclib.txt).
_LIB_CANDIDATES = (
    Path(os.environ.get("HOME", "/home")) / "matiec" / "lib",
    Path("/usr/local/share/matiec") / "lib",
    Path("/usr/share/matiec") / "lib",
)


@dataclass
class CompilationResult:
    """Outcome of a single ``iec2c`` compilation run."""

    compiled: bool
    returncode: int
    stdout: str = ""
    stderr: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def first_error(self) -> str:
        return self.errors[0] if self.errors else ""


def is_matiec_available() -> bool:
    """Return True if ``iec2c`` is on the system PATH."""
    return shutil.which("iec2c") is not None


def _find_matiec_lib() -> Path | None:
    """Locate a directory containing the MATIEC standard library (ieclib.txt)."""
    override = os.environ.get("MATIEC_LIB")
    candidates = [Path(override)] if override else list(_LIB_CANDIDATES)
    for cand in candidates:
        if (cand / "ieclib.txt").exists():
            return cand
    return None


def _strip_line_comments(code: str) -> str:
    """Strip ``//`` line comments (MATIEC only accepts ``(* *)`` comments)."""
    return re.sub(r"//.*$", "", code, flags=re.M)


def _program_name(code: str) -> str | None:
    m = re.search(r"^\s*PROGRAM\s+([A-Za-z_]\w*)", code, flags=re.M)
    return m.group(1) if m else None


def _configuration_wrapper(program_name: str) -> str:
    """Synthesize a minimal IEC 61131-3 CONFIGURATION/RESOURCE/TASK wrapper.

    TASK priority names follow IEC 61131-3 (priority 0 = highest).
    """
    return (
        "\n"
        "CONFIGURATION main_cfg\n"
        "    RESOURCE res1 ON PLC\n"
        f"        TASK main_t(INTERVAL := T#1s, PRIORITY := 0);\n"
        f"        PROGRAM main_p WITH main_t : {program_name};\n"
        "    END_RESOURCE\n"
        "END_CONFIGURATION\n"
    )


def compile_st_file(
    st_path: Path | str,
    extra_flags: list[str] | None = None,
    with_configuration: bool = False,
) -> CompilationResult:
    """Compile an ST file with ``iec2c`` and return the result.

    Parameters
    ----------
    st_path:
        Path to a ``.st`` file.
    extra_flags:
        Optional extra ``iec2c`` command-line flags.
    with_configuration:
        When True, wrap the ``PROGRAM`` in a synthesized minimal
        ``CONFIGURATION``/``RESOURCE``/``TASK`` before compiling.

    Temporary compile directories are always cleaned up.
    """
    flags = list(extra_flags) if extra_flags else []

    if not is_matiec_available():
        raise RuntimeError("iec2c not found on PATH; cannot compile")
    lib_dir = _find_matiec_lib()
    if lib_dir is None:
        raise RuntimeError("could not locate MATIEC library (ieclib.txt)")

    workdir = tempfile.mkdtemp(prefix="matiec_")
    try:
        shutil.copytree(lib_dir, Path(workdir) / "lib", dirs_exist_ok=True)

        source = Path(st_path).read_text(encoding="utf-8")
        code = _strip_line_comments(source)
        program_name = _program_name(code)
        if with_configuration and program_name:
            code += _configuration_wrapper(program_name)

        src_name = Path(st_path).name
        src_path = Path(workdir) / src_name
        src_path.write_text(code, encoding="utf-8")

        proc = subprocess.run(
            ["iec2c", *flags, src_name],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        combined = proc.stdout + proc.stderr
        errors = [
            ln.strip()
            for ln in combined.splitlines()
            if "error" in ln.lower()
        ]
        return CompilationResult(
            compiled=(proc.returncode == 0),
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            errors=errors,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

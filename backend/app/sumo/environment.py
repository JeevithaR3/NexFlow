"""Detect the SUMO installation and report a clear status with setup instructions."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import SumoUnavailableError

SETUP_HELP = (
    "Install SUMO (https://sumo.dlr.de/docs/Downloads.php), then either add its 'bin' folder to PATH, "
    "set SUMO_HOME, or set NEXFLOW_SUMO_BINARY to the full path of the 'sumo' executable. "
    "Alternatively run: pip install eclipse-sumo traci sumolib."
)


@dataclass
class SumoStatus:
    available: bool
    sumo_binary: str | None = None
    sumo_gui_binary: str | None = None
    netconvert_binary: str | None = None
    netgenerate_binary: str | None = None
    version: str | None = None
    sumo_home: str | None = None
    traci_importable: bool = False
    sumolib_importable: bool = False
    problems: list[str] = field(default_factory=list)
    help: str = SETUP_HELP

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _candidate_dirs() -> list[Path]:
    dirs: list[Path] = [Path(sys.executable).parent]
    home = os.environ.get("SUMO_HOME")
    if home:
        dirs.append(Path(home) / "bin")
    try:  # the `eclipse-sumo` pip wheel
        import sumo  # type: ignore

        dirs.append(Path(sumo.SUMO_HOME) / "bin")
    except Exception:
        pass
    return dirs


def find_binary(name: str) -> str | None:
    exe = name + (".exe" if os.name == "nt" else "")
    found = shutil.which(name)
    if found:
        return found
    for d in _candidate_dirs():
        p = d / exe
        if p.exists():
            return str(p)
    return None


def sumo_home() -> str | None:
    home = os.environ.get("SUMO_HOME")
    if home and Path(home).exists():
        return home
    try:
        import sumo  # type: ignore

        return str(sumo.SUMO_HOME)
    except Exception:
        return None


def check_sumo() -> SumoStatus:
    s = get_settings()
    problems: list[str] = []
    binary = s.sumo_binary if s.sumo_binary and Path(s.sumo_binary).exists() else None
    if s.sumo_binary and not binary:
        problems.append(f"NEXFLOW_SUMO_BINARY points to a missing file: {s.sumo_binary}")
    binary = binary or find_binary("sumo")
    status = SumoStatus(
        available=False,
        sumo_binary=binary,
        sumo_gui_binary=find_binary("sumo-gui"),
        netconvert_binary=find_binary("netconvert"),
        netgenerate_binary=find_binary("netgenerate"),
        sumo_home=sumo_home(),
    )
    try:
        import traci  # noqa: F401

        status.traci_importable = True
    except Exception as exc:
        problems.append(f"Python package 'traci' not importable ({type(exc).__name__}). pip install traci")
    try:
        import sumolib  # noqa: F401

        status.sumolib_importable = True
    except Exception as exc:
        problems.append(f"Python package 'sumolib' not importable ({type(exc).__name__}). pip install sumolib")
    if not binary:
        problems.append("'sumo' executable not found")
    else:
        try:
            out = subprocess.run(
                [binary, "--version"], capture_output=True, text=True, timeout=20, check=False
            ).stdout
            m = re.search(r"SUMO\s+(?:sumo\s+)?v?([\d.]+)", out)
            status.version = m.group(1) if m else out.strip().splitlines()[0] if out.strip() else None
        except Exception as exc:
            problems.append(f"could not execute '{binary}': {type(exc).__name__}")
    status.problems = problems
    status.available = bool(binary and status.traci_importable and status.sumolib_importable and status.version)
    return status


def require_sumo() -> SumoStatus:
    st = check_sumo()
    if not st.available:
        raise SumoUnavailableError("SUMO is not available: " + "; ".join(st.problems or ["unknown problem"]), hint=SETUP_HELP)
    return st

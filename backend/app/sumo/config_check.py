"""Validate a ``.sumocfg`` before starting a simulation."""
from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from app.core.errors import SumoConfigError
from app.sumo.environment import require_sumo


def validate_sumocfg(cfg: Path | str, dry_run: bool = True) -> dict:
    cfg = Path(cfg)
    problems: list[str] = []
    if not cfg.exists():
        raise SumoConfigError(f"SUMO configuration not found: {cfg.name}", hint="Run scripts/generate_network.py")
    try:
        root = ET.parse(cfg).getroot()
    except ET.ParseError as exc:
        raise SumoConfigError(f"SUMO configuration '{cfg.name}' is not valid XML: {exc}") from exc
    if root.tag != "configuration":
        problems.append("root element must be <configuration>")
    refs: dict[str, list[Path]] = {}
    for tag in ("net-file", "route-files", "additional-files"):
        for el in root.iter(tag):
            val = el.get("value", "")
            files = [(cfg.parent / v.strip()).resolve() for v in val.split(",") if v.strip()]
            refs.setdefault(tag, []).extend(files)
            for f in files:
                if not f.exists():
                    problems.append(f"{tag} references a missing file: {f.name}")
    if "net-file" not in refs:
        problems.append("no <net-file> specified")
    if "route-files" not in refs:
        problems.append("no <route-files> specified")
    if problems:
        raise SumoConfigError("Invalid SUMO configuration: " + "; ".join(problems))
    if dry_run:
        st = require_sumo()
        res = subprocess.run(
            [st.sumo_binary, "-c", str(cfg), "--end", "1", "--no-step-log", "true", "--no-warnings", "true",
             "--duration-log.disable", "true"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        if res.returncode != 0:
            msg = (res.stderr or res.stdout).strip().splitlines()
            raise SumoConfigError("SUMO rejected the configuration: " + (msg[0] if msg else "unknown error")[:300])
    return {"ok": True, "config": str(cfg), "net_file": str(refs["net-file"][0]), "route_files": [str(p) for p in refs["route-files"]]}

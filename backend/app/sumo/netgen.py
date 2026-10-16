"""Generate the demonstration SUMO files with SUMO's own tools (no hand-written XML network)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import SumoConfigError
from app.digital_twin.network import load_network
from app.sumo.environment import require_sumo
from app.sumo.scenario import ScenarioConfig, write_route_file

SUMOCFG_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!-- NexFlow demonstration scenario. Run standalone with: sumo -c simulation.sumocfg (or sumo-gui) -->
<configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/sumoConfiguration.xsd">
    <input>
        <net-file value="../network/network.net.xml"/>
        <route-files value="../routes/routes.rou.xml"/>
    </input>
    <time>
        <begin value="0"/>
        <end value="{duration}"/>
        <step-length value="1"/>
    </time>
    <processing>
        <waiting-time-memory value="3600"/>
    </processing>
    <random_number>
        <seed value="1"/>
    </random_number>
    <report>
        <no-step-log value="true"/>
        <duration-log.disable value="true"/>
    </report>
</configuration>
"""


def generate_demo_files(grid: int = 3, block_m: float = 200.0, force: bool = True) -> dict[str, str]:
    """Create network.net.xml, routes.rou.xml and simulation.sumocfg."""
    s = get_settings()
    st = require_sumo()
    if not st.netgenerate_binary:
        raise SumoConfigError("'netgenerate' not found", hint="Install the full SUMO package (it ships netgenerate).")
    net_file = s.network_file
    net_file.parent.mkdir(parents=True, exist_ok=True)
    if force or not net_file.exists():
        cmd = [
            st.netgenerate_binary, "--grid", "--grid.number", str(grid), "--grid.length", str(block_m),
            "--grid.attach-length", str(block_m), "--default.lanenumber", "1", "--default.speed", "13.89",
            "--default-junction-type", "traffic_light", "--no-turnarounds", "true",
            "--output-file", str(net_file), "--no-warnings", "true",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
        if res.returncode != 0 or not net_file.exists():
            raise SumoConfigError("netgenerate failed", hint=res.stderr.strip()[:300])
    net = load_network(net_file)
    sc = ScenarioConfig(pattern="ew_heavy", demand_scale=1.0, seed=1, duration_s=s.scenario_duration_s)
    routes = s.simulation_dir / "routes" / "routes.rou.xml"
    n_trips = write_route_file(net, sc, routes)
    s.sumocfg_file.parent.mkdir(parents=True, exist_ok=True)
    s.sumocfg_file.write_text(SUMOCFG_TEMPLATE.format(duration=sc.duration_s), encoding="utf-8")
    return {
        "network": str(net_file), "routes": str(routes), "config": str(s.sumocfg_file),
        "edges": str(net.n_edges), "junctions": str(len(net.junctions)), "trips": str(n_trips),
    }

"""Download local OSM road extracts around the five TomTom sensors and convert them to SUMO."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import _path  # noqa: F401
from app.core.config import get_settings
from app.core.errors import NexFlowError, SumoConfigError
from app.services.tomtom_traffic import SENSORS
from app.sumo.environment import require_sumo


RADIUS_DEGREES = 0.0025
SUMOCFG = """<?xml version="1.0" encoding="UTF-8"?>
<configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/sumoConfiguration.xsd">
  <input>
    <net-file value="bengaluru-five-local.net.xml"/>
    <route-files value="routes-placeholder.rou.xml"/>
  </input>
  <time><begin value="0"/><end value="1260"/><step-length value="1"/></time>
  <processing><waiting-time-memory value="3600"/></processing>
  <report><no-step-log value="true"/><duration-log.disable value="true"/></report>
</configuration>
"""


def _download(sensor, destination: Path) -> None:
    south = sensor.latitude - RADIUS_DEGREES
    north = sensor.latitude + RADIUS_DEGREES
    west = sensor.longitude - RADIUS_DEGREES
    east = sensor.longitude + RADIUS_DEGREES
    url = f"https://api.openstreetmap.org/api/0.6/map?bbox={west},{south},{east},{north}"
    request = Request(url, headers={"User-Agent": "NexFlow-development/1.0 (Bengaluru SUMO setup)"})
    try:
        with urlopen(request, timeout=90) as response:
            if response.status != 200:
                raise SumoConfigError(f"OpenStreetMap returned HTTP {response.status} for {sensor.road_name}.")
            data = response.read()
    except (TimeoutError, URLError) as exc:
        raise SumoConfigError(
            f"Could not download OpenStreetMap roads near {sensor.road_name}.",
            hint="Check internet access and retry scripts/setup_bengaluru_sumo.py.",
        ) from exc
    if b"<osm" not in data[:1000]:
        raise SumoConfigError(f"OpenStreetMap returned invalid map data for {sensor.road_name}.")
    destination.write_bytes(data)


def setup() -> dict[str, str]:
    settings = get_settings()
    sumo = require_sumo()
    if not sumo.netconvert_binary:
        raise SumoConfigError("SUMO netconvert is not available.", hint="Install the full SUMO package.")
    osm_dir = settings.bengaluru_sumo_dir / "osm"
    osm_dir.mkdir(parents=True, exist_ok=True)
    osm_files = []
    for sensor in SENSORS:
        destination = osm_dir / f"{sensor.id}.osm.xml"
        _download(sensor, destination)
        osm_files.append(destination)

    net_file = settings.bengaluru_network_file
    cmd = [
        sumo.netconvert_binary,
        "--osm-files", ",".join(str(path) for path in osm_files),
        "--output-file", str(net_file),
        "--tls.guess", "true",
        "--no-turnarounds", "true",
        "--keep-edges.by-vclass", "passenger",
        "--no-warnings", "true",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
    if result.returncode != 0 or not net_file.exists():
        raise SumoConfigError(
            "SUMO could not convert the Bengaluru OpenStreetMap extracts.",
            hint=(result.stderr or result.stdout).strip()[:300] or "See the SUMO installation and OSM setup.",
        )
    settings.bengaluru_sumocfg_file.write_text(SUMOCFG, encoding="utf-8")
    (settings.bengaluru_sumo_dir / "routes-placeholder.rou.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<routes/>\n', encoding="utf-8"
    )
    return {"network": str(net_file), "sumocfg": str(settings.bengaluru_sumocfg_file),
            "osm_extracts": str(len(osm_files))}


if __name__ == "__main__":
    try:
        for key, value in setup().items():
            print(f"{key:14s} {value}")
    except NexFlowError as exc:
        print(f"ERROR: {exc.message}\n{exc.hint or ''}")
        sys.exit(1)

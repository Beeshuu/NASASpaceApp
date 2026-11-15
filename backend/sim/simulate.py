"""Simulated crew for Vital Orbit Pulse: 3 astronauts, 180-day mission, six health domains.

Streams normalized readings to the ingest endpoint. Standard library only.

    python sim/simulate.py --key dev-ingest-key                      # 1 mission minute per second
    python sim/simulate.py --key ... --step 21600 --day 30           # 6 mission hours per second
    python sim/simulate.py --key ... --anomaly tachycardia:okafor@30 --anomaly co2:hab-a@45
    python sim/simulate.py --dry-run --ticks 1                       # print instead of sending

CO2 builds up gradually (0.15 mmHg per tick), so the twin can forecast it before it gets high.
Anomalies: co2, hypoxia (module or crew member), tachycardia, bone, mood, fever (crew member).
@N starts the anomaly at tick N, so personal baselines are learned from normal readings first.

Radiation is not simulated here. It is the crew dose the Worker models from real NASA CCMC DONKI
space weather events, read from /api/space-weather/dose. The mission starts on 1 May 2024.
Everything else is simulated data, not real astronaut data.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from crew_sim import CREW, MISSION_START, SHIELDING, dose_at, readings  # noqa: E402  (shared with the Worker's demo replay)

MISSION_DAYS = 180
# Cloudflare Access service token vop-simulator, needed against vitalorbit.health (PROGRESS.md, phase 13).
ACCESS = {h: os.environ[v] for h, v in (("CF-Access-Client-Id", "CF_ACCESS_CLIENT_ID"), ("CF-Access-Client-Secret", "CF_ACCESS_CLIENT_SECRET")) if os.environ.get(v)}


def modeled_dose(url, end):
    """Unshielded crew dose modeled from DONKI events, mission start to `end`: [[ts ms, mSv/day, cumulative mSv], ...]."""
    query = f"/api/space-weather/dose?start={MISSION_START.date()}&end={end.date()}&step_min=60"
    data = json.load(urllib.request.urlopen(urllib.request.Request(url + query, headers=ACCESS), timeout=300))
    if data["missing"]:
        print(f"WARNING: DONKI did not answer for {', '.join(data['missing'])}. The dose leaves those events out.")
    return data["points"]


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--url", default="http://127.0.0.1:8787")
    p.add_argument("--key", default="", help="value of INGEST_KEY")
    p.add_argument("--day", type=float, default=0, help="mission day to start from")
    p.add_argument("--step", type=float, default=60, help="mission seconds per tick")
    p.add_argument("--tick", type=float, default=1, help="real seconds per tick")
    p.add_argument("--ticks", type=int, default=0, help="stop after this many ticks (0 = run until day 180)")
    p.add_argument("--anomaly", action="append", default=[], metavar="NAME:TARGET[@TICK]", help="e.g. co2:hab-a, fever:reyes@30")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    anomalies = []
    for spec in a.anomaly:
        name, _, rest = spec.partition(":")
        target, _, start = rest.partition("@")
        assert target in CREW or target in SHIELDING, f"{spec}: use NAME:TARGET[@TICK], target = crew member or module"
        anomalies.append((name, target, int(start or 0)))

    t = MISSION_START + timedelta(days=a.day)
    mission_end = MISSION_START + timedelta(days=MISSION_DAYS)
    end = min(mission_end, t + timedelta(seconds=a.step * a.ticks)) if a.ticks else mission_end
    # A dry run stays offline, so it carries only the quiet background rate.
    dose = [[0, 0.65, 0], [mission_end.timestamp() * 1000, 0.65, 0.65 * MISSION_DAYS]] if a.dry_run else modeled_dose(a.url, end)
    last_day, n = None, 0
    while t < mission_end and (not a.ticks or n < a.ticks):
        batch = []
        for entity, module in CREW.items():
            active = {name: n - start + 1 for name, target, start in anomalies if target in (entity, module) and n >= start}
            batch += readings(entity, module, t, t.date() != last_day, active, dose_at(dose, t))
        last_day = t.date()
        if a.dry_run:
            print(len(batch), "readings at", t.isoformat(), "sample:", json.dumps(batch[0]))
        else:
            req = urllib.request.Request(a.url + "/api/ingest", json.dumps(batch).encode(),
                                         {"content-type": "application/json", "x-ingest-key": a.key, **ACCESS})  # fmt: skip
            urllib.request.urlopen(req, timeout=30).read()
            print(f"sent {len(batch)} readings, mission day {(t - MISSION_START).total_seconds() / 86400:.2f}")
        t += timedelta(seconds=a.step)
        n += 1
        time.sleep(0 if a.dry_run else a.tick)


if __name__ == "__main__":
    main()

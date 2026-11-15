"""Simulated crew readings, shared by sim/simulate.py and the Worker's demo replay. Standard library only.

Everything here is simulated data, not real astronaut data. Radiation comes from the dose the Worker
models from real NASA CCMC DONKI space weather events.
"""

import bisect
import math
import random
from datetime import datetime, timezone

MISSION_START = datetime(2024, 5, 1, tzinfo=timezone.utc)
CREW = {"okafor": "hab-a", "reyes": "hab-a", "lindqvist": "lab"}
SHIELDING = {"hab-a": 1.0, "lab": 0.6}  # the lab is the shielded module
BASE_HR = {"okafor": 58, "reyes": 66, "lindqvist": 62}


def dose_at(points, t):
    """(rate, cumulative) at time t, interpolated between the hourly points."""
    ts = t.timestamp() * 1000
    i = min(max(bisect.bisect_right(points, [ts]), 1), len(points) - 1)
    a, b = points[i - 1], points[i]
    f = min(max((ts - a[0]) / (b[0] - a[0]), 0), 1)
    return a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2])


def readings(entity, module, t, day_start, active, dose):
    """All readings for one crew member at mission time t. `active` maps each anomaly hitting them to ticks since it began."""
    day = (t - MISSION_START).total_seconds() / 86400
    hour = t.hour + t.minute / 60
    awake = 0.5 + 0.5 * math.sin((hour - 9) / 24 * 2 * math.pi)  # 0 asleep .. 1 mid-day
    g = random.gauss
    out = []

    def add(domain, metric, value, unit, source, meta=None):
        row = {"entity_id": entity, "timestamp": t.isoformat(), "domain": domain, "metric": metric,
               "value": round(value, 2), "unit": unit, "source": source}  # fmt: skip
        if meta:
            row["meta"] = meta
        out.append(row)

    tachy = "tachycardia" in active
    add("cardiovascular", "heart_rate", BASE_HR[entity] + 14 * awake + g(0, 2) + (55 if tachy else 0), "bpm", "wearable")
    add("cardiovascular", "hrv", 62 - 12 * awake + g(0, 3) - (30 if tachy else 0), "ms", "wearable")
    add("cardiovascular", "blood_pressure_systolic", 114 + 6 * awake + g(0, 2) + (18 if tachy else 0), "mmHg", "wearable")
    add("cardiovascular", "blood_pressure_diastolic", 74 + 3 * awake + g(0, 1.5), "mmHg", "wearable")
    add("immune", "body_temperature", 36.7 + 0.3 * awake + g(0, 0.05) + (1.7 if "fever" in active else 0), "°C", "wearable")

    env = {"module": module}
    add("environment", "co2", 2.6 + g(0, 0.1) + min(4.5, 0.15 * active.get("co2", 0)), "mmHg", "environment_sensor", env)
    add("environment", "o2", 20.9 + g(0, 0.05) - (4.2 if "hypoxia" in active else 0), "%", "environment_sensor", env)
    add("environment", "air_quality_pm25", 8 + g(0, 1), "µg/m³", "environment_sensor", env)

    rate, total = dose
    add("radiation", "dose_rate", rate * SHIELDING[module], "mSv/day", "modeled_from_donki")
    add("radiation", "cumulative_dose", total * SHIELDING[module], "mSv", "modeled_from_donki")

    if day_start:  # once per mission day: self-tests and self-reports
        low = "mood" in active
        add("bone", "exercise_minutes", max(0, g(20 if "bone" in active else 130, 15)), "min", "self_report")
        add("bone", "bone_density", 100 - (0.045 if "bone" in active else 0.012) * day, "% of baseline", "self_test")
        add("behavioral", "mood", min(5, max(1, round(g(2 if low else 4, 0.5)))), "1-5", "self_report")
        add("behavioral", "sleep_hours", max(2, g(4.8 if low else 7.2, 0.5)), "h", "self_report")
        add("behavioral", "reaction_time", g(340 if low else 265, 12), "ms", "self_test")
    return out

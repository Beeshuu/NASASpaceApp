"""Space weather: NASA DONKI events, where Earth and Mars are, and the crew dose modeled from both.

Pure Python with no Workers imports, so it runs under plain CPython for tests.
The dose model is illustrative. It is not dosimetry.
"""

import math
from datetime import datetime

import astronomy

KINDS = ("FLR", "CME", "SEP", "GST")
AU_KM = 149_597_870.7
LIGHT_S_PER_AU = 499.004784
CME_START_AU = 0.1  # DONKI reports each CME at 21.5 solar radii, which is 0.1 AU


def ms(iso):
    """DONKI time such as "2024-05-10T02:12Z" to epoch milliseconds."""
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000) if iso else None


def normalize(kind, raw):
    """Raw DONKI records of one kind to the flat events this app stores."""
    out = []
    for e in raw or []:
        if kind == "FLR":
            row = {
                "id": e["flrID"],
                "time": ms(e.get("beginTime")),
                "peak": ms(e.get("peakTime")),
                "class": e.get("classType"),
                "source": e.get("sourceLocation"),
            }
        elif kind == "CME":
            row = {"id": e["activityID"], "time": ms(e.get("startTime")), "source": e.get("sourceLocation")}
            a = next((x for x in e.get("cmeAnalyses") or [] if x.get("isMostAccurate")), None)
            if a and a.get("speed") and a.get("halfAngle") and a.get("longitude") is not None and a.get("time21_5"):
                row.update(speed=a["speed"], lon=a["longitude"], lat=a.get("latitude"), half_angle=a["halfAngle"], t21_5=ms(a["time21_5"]))
                row["mars_arrival"] = mars_arrival(row)
        elif kind == "SEP":
            row = {
                "id": e["sepID"],
                "time": ms(e.get("eventTime")),
                "instruments": [i["displayName"] for i in e.get("instruments") or []],
            }
        else:
            kp = [k["kpIndex"] for k in e.get("allKpIndex") or []]
            row = {"id": e["gstID"], "time": ms(e.get("startTime")), "kp_max": max(kp, default=None)}
        if row["time"] is None:
            continue
        row.update(type=kind, link=e.get("link"), linked=[x["activityID"] for x in e.get("linkedEvents") or []])
        out.append(row)
    return out


def _helio(body, ts):
    """Heliocentric ecliptic position in AU."""
    time = astronomy.Time(ts / 86_400_000 - 10957.5)  # days since J2000
    return astronomy.Ecliptic(astronomy.HelioVector(body, time)).vec


def sky(ts):
    """Where Earth and Mars are at epoch ms `ts`, and how long light takes between them."""
    e, m = _helio(astronomy.Body.Earth, ts), _helio(astronomy.Body.Mars, ts)
    distance = math.dist((e.x, e.y, e.z), (m.x, m.y, m.z))
    return {"earth": [e.x, e.y], "mars": [m.x, m.y], "distance_au": distance, "light_s": distance * LIGHT_S_PER_AU}


def mars_arrival(cme):
    """When this CME's front reaches Mars (epoch ms), or None if its cone misses Mars."""
    s = sky(cme["t21_5"])
    # DONKI longitude is measured from the Sun-Earth line, positive in the direction the planets orbit.
    mars_from_earth = math.degrees(math.atan2(s["mars"][1], s["mars"][0]) - math.atan2(s["earth"][1], s["earth"][0]))
    off_axis = (cme["lon"] - mars_from_earth + 180) % 360 - 180
    if abs(off_axis) > cme["half_angle"]:
        return None
    # shortcut: constant speed and Mars held where it was at launch, good to a few hours over a few days
    travel_s = (math.hypot(*s["mars"]) - CME_START_AU) * AU_KM / cme["speed"]
    return cme["t21_5"] + round(travel_s * 1000)


def triggers(events):
    """DONKI events as playbook triggers, oldest first: SEP onsets, and CME fronts arriving at Mars."""
    out = [{"event": "sep_onset", "id": e["id"], "ts": e["time"]} for e in events if e["type"] == "SEP"]
    out += [{"event": "cme_arrival", "id": e["id"], "ts": e["mars_arrival"]} for e in events if e["type"] == "CME" and e.get("mars_arrival")]
    return sorted(out, key=lambda t: t["ts"])


def flare_factor(cls):
    """Flare class to a scale factor: X1 is 1, M1 is 0.1, C1 is 0.01."""
    scale = {"X": 1, "M": 0.1, "C": 0.01}.get((cls or " ")[0])
    try:
        return scale * float(cls[1:]) if scale else None
    except ValueError:
        return None


def dose_series(events, start, end, step, model, shielding=1.0):
    """Modeled crew dose at Mars: [[ts, rate in mSv/day, cumulative mSv since start], ...].

    Quiet background, plus a decaying burst for each solar energetic particle event (scaled by the
    strongest flare DONKI links to it), plus a bump when a CME whose cone covers Mars arrives.
    """
    flares = {e["id"]: flare_factor(e.get("class")) for e in events if e["type"] == "FLR"}
    sources = []  # (time, peak mSv/day, time constant ms, also rises before the time)
    for e in events:
        if e["type"] == "SEP":
            linked = [flares[x] for x in e["linked"] if flares.get(x)]
            factor = max(linked, default=model.unlinked_flare_factor)
            sources.append((e["time"], model.sep_peak * factor, model.sep_decay_hours * 3_600_000, False))
        elif e["type"] == "CME" and e.get("mars_arrival"):
            sources.append((e["mars_arrival"], model.shock_peak * e["speed"] / 1000, model.shock_hours * 3_600_000, True))

    points, total, t = [], 0.0, start
    while t <= end:
        rate = model.quiet_rate
        for t0, peak, tau, two_sided in sources:
            if t >= t0 or two_sided:
                rate += peak * math.exp(-abs(t - t0) / tau)
        rate *= shielding
        points.append([t, round(rate, 3), round(total, 3)])
        total += rate * step / 86_400_000
        t += step
    return points

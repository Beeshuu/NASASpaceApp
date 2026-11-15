"""Engine self-check. Run: uv run python tests/test_engine.py"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

import engine  # noqa: E402

text = (ROOT / "playbooks" / "archive" / "crew-health.yaml").read_text(encoding="utf-8")
pb = engine.load_playbook(text)
assert pb.name == "crew-health" and len(pb.rules) >= 10

# Broken references are rejected.
for bad in (
    text.replace("do: alert_crew", "do: launch_rocket", 1),
    text.replace("metric: heart_rate", "metric: hart_rate", 1),
    text.replace("checklist: heart_elevated }", "checklist: nope }", 1),
    text.replace("severity: act", "severity: panic", 1),
    text + "\nsurprise: true\n",
    # a drift rule on an indicator that opts out of baselines
    text.replace("heart_rate: { label: Heart rate, unit: bpm }", "heart_rate: { label: Heart rate, unit: bpm, baseline: false }"),
):
    try:
        engine.load_playbook(bad)
    except ValueError:
        continue
    raise AssertionError("invalid playbook was accepted")


def feed(state, metric, values, domain="cardiovascular", t0=0):
    events = []
    for i, v in enumerate(values):
        events += engine.step(pb, state, {"domain": domain, "metric": metric, "value": v, "ts": t0 + i})
    return events


# Acute drift: learn a baseline of 60, then a sustained jump fires once and clears once.
s = engine.new_state()
assert feed(s, "heart_rate", [60] * 20) == []
assert s["metrics"]["cardiovascular/heart_rate"]["learned"]
assert feed(s, "heart_rate", [120, 120], t0=100) == [], "sustain: 3 must not fire on two readings"
fired = feed(s, "heart_rate", [120, 120], t0=102)
assert [e["type"] for e in fired] == ["fired"], fired
a = fired[0]["alert"]
assert a["severity"] == "act" and a["baseline"] == 60 and a["checklist"] == "heart_elevated"
assert a["alert_crew"] and a["paged"] == ["flight_surgeon"] and a["logged"]
st = engine.status(pb, s)
assert st["overall"] == "act" and st["domains"] == {"cardiovascular": "act"} and len(st["alerts"]) == 1
assert [e["type"] for e in feed(s, "heart_rate", [62], t0=200)] == ["cleared"]
assert engine.status(pb, s)["overall"] is None

# A drift rule stays quiet while the baseline is still being learned.
s = engine.new_state()
assert feed(s, "heart_rate", [60, 200, 200, 200, 200]) == []
assert "cardiovascular/heart_rate" in engine.status(pb, s)["learning"]

# Threshold needs no baseline.
s = engine.new_state()
assert [e["type"] for e in feed(s, "dose_rate", [26], domain="radiation")] == ["fired"]

# Chronic drift reads the slow trend: a steady decline fires, a single dip does not.
s = engine.new_state()
feed(s, "bone_density", [100, 100, 100], domain="bone")
assert feed(s, "bone_density", [90], domain="bone", t0=10) == []
s = engine.new_state()
feed(s, "bone_density", [100, 100, 100], domain="bone")
decline = feed(s, "bone_density", [100 - 0.3 * d for d in range(1, 40)], domain="bone", t0=10)
assert [e["alert"]["rule"] for e in decline] == ["bone_density_declining"], decline

# Worst severity wins per domain; a metric outside the playbook is ignored.
s = engine.new_state()
feed(s, "co2", [7, 7], domain="environment")
st = engine.status(pb, s)
assert st["domains"] == {"environment": "act"} and [a["severity"] for a in st["alerts"]] == ["act"]
assert engine.step(pb, s, {"domain": "x", "metric": "y", "value": 1, "ts": 0}) == []

# Check-in answers are validated against the playbook and become readings.
good = {"mood": 4, "sleep_hours": 7.5, "reaction_time": 280, "symptoms": "sore throat"}
readings, kept = engine.checkin_readings(pb, good)
assert [(r["metric"], r["value"], r["source"]) for r in readings] == [
    ("mood", 4, "self_report"),
    ("sleep_hours", 7.5, "self_report"),
    ("reaction_time", 280, "self_test"),
]
assert kept == good
for wrong in ({**good, "mood": 9}, {**good, "sleep_hours": "seven"}, {"mood": 4, "sleep_hours": 7}):
    try:
        engine.checkin_readings(pb, wrong)
    except ValueError:
        continue
    raise AssertionError(f"bad check-in was accepted: {wrong}")

# Twin forecast: a steady climb toward the budget fires before the threshold is reached, with a crossing time.
DAY = 86_400_000
s = engine.new_state()
events = []
for d in range(140):
    events += engine.step(pb, s, {"domain": "radiation", "metric": "cumulative_dose", "value": 0.65 * d, "ts": d * DAY})
fired = [e for e in events if e["type"] == "fired" and e["alert"]["rule"] == "mission_dose_budget_forecast"]
assert len(fired) == 1 and fired[0]["alert"]["value"] < 100, fired
fc = next(f for f in engine.status(pb, s)["forecasts"] if f["rule"] == "mission_dose_budget_forecast")
assert 225 <= fc["eta"] / DAY <= 236, fc["eta"] / DAY  # 150 / 0.65 is day 231
assert len(fc["points"]) <= engine.HISTORY and fc["points"][0][0] <= 3 * DAY, "history must still reach the start"

# Sensor rounding at one reading a minute must not inflate the slope: 0.65 mSv/day in 0.01 steps is still day 231.
s = engine.new_state()
events = []
for minute in range(30 * 1440):
    reading = {"domain": "radiation", "metric": "cumulative_dose", "value": round(0.65 * minute / 1440, 2), "ts": minute * 60_000}
    events += engine.step(pb, s, reading)
assert not [e for e in events if e["alert"]["rule"] == "mission_dose_budget_forecast"], "fired 200 days early"

# A steady bone density decline is forecast before the chronic drift rule catches it.
s = engine.new_state()
events = []
for d in range(80):
    events += engine.step(pb, s, {"domain": "bone", "metric": "bone_density", "value": 100 - 0.045 * d, "ts": d * DAY})
assert [e["alert"]["rule"] for e in events][:1] == ["bone_density_forecast"], events

# A flat series never forecasts a crossing, and neither does one heading away from the threshold.
s = engine.new_state()
flat = [engine.step(pb, s, {"domain": "bone", "metric": "bone_density", "value": 100, "ts": d * DAY}) for d in range(30)]
assert not any(flat) and engine.status(pb, s)["forecasts"][0]["eta"] is None

# baseline: false is never learned.
s = engine.new_state()
feed(s, "cumulative_dose", [1.0] * 30, domain="radiation")
assert "radiation/cumulative_dose" not in engine.status(pb, s)["baselines"]

# Space weather: real DONKI records from 10 to 11 May 2024.
import json  # noqa: E402

import space  # noqa: E402


def fixture(kind):
    path = ROOT / "tests" / "fixtures" / f"donki_{kind}_2024-05-10.json"
    return space.normalize(kind, json.loads(path.read_text(encoding="utf-8")))


sep, cme, gst = fixture("SEP"), fixture("CME"), fixture("GST")
assert len(sep) == 6 and len(cme) == 11 and gst[0]["kp_max"] == 9.0
assert sep[0]["linked"][0] == "2024-05-09T08:45:00-FLR-001" and sep[0]["time"] == space.ms("2024-05-10T12:59Z")
fast = next(c for c in cme if c["id"] == "2024-05-10T07:12:00-CME-001")
assert (fast["speed"], fast["lon"], fast["half_angle"]) == (1018.0, 31.0, 41.0)
assert "speed" not in next(c for c in cme if c["id"] == "2024-05-10T16:36:00-CME-001"), "no analysis, no cone"

# Earth and Mars on 10 May 2024: Mars was 1.94 AU away, on the far side, so Earth-directed CMEs miss it.
sky = space.sky(space.ms("2024-05-10T12:00Z"))
assert 1.93 < sky["distance_au"] < 1.95 and 960 < sky["light_s"] < 975, sky
assert fast["mars_arrival"] is None
toward_mars = next(c for c in cme if c["id"] == "2024-05-11T18:00:00-CME-001")
assert 8 < (toward_mars["mars_arrival"] - toward_mars["t21_5"]) / DAY < 10, "268 km/s over about 1.5 AU"

# Modeled dose: quiet before the events, a burst at each particle event, a bump when the CME reaches Mars.
assert space.flare_factor("X5.8") == 5.8 and space.flare_factor("M1.0") == 0.1 and space.flare_factor(None) is None
model = pb.space_weather.model
start, HOUR = space.ms("2024-05-10T00:00Z"), 3_600_000
series = space.dose_series(sep + cme + gst, start, start + 12 * DAY, HOUR, model)
rate = {t: r for t, r, _ in series}
assert rate[start] == model.quiet_rate
assert rate[start + 14 * HOUR] > 5 * model.quiet_rate, "six particle events on 10 May"
arrival = toward_mars["mars_arrival"] // HOUR * HOUR
assert rate[arrival] > rate[arrival - 2 * DAY] + 0.5, "CME front at Mars"
assert series[-1][2] > 12 * model.quiet_rate, "cumulative dose is above the quiet-only total"
half = space.dose_series(sep, start, start + DAY, HOUR, model, shielding=0.5)
assert half[14][1] == round(series[14][1] / 2, 3) or abs(half[14][1] - series[14][1] / 2) < 0.01

# Assistant prompt: built only from the playbook and the crew member's own state.
assert pb.ai.role == "Flight surgeon assistant" and "never diagnose" in pb.ai.prompt
assert len(pb.knowledge) == 7 and all(len(d.text) <= 1500 for d in pb.knowledge)
s = engine.new_state()
feed(s, "co2", [7, 7], domain="environment")
st = engine.status(pb, s)
text = engine.explain_prompt(pb, st, st["alerts"][0], "Is this dangerous?", pb.knowledge[1:2])
assert "Is this dangerous?" in text and "Carbon dioxide in your module is high." in text
assert "Carbon dioxide is 7 mmHg" in text and "1. Tell everyone in this module." in text
assert "Guidance [Carbon dioxide in a closed cabin]" in text
assert "No alert is active" in engine.explain_prompt(pb, engine.status(pb, engine.new_state()), None, "hi", [])
try:
    engine.load_playbook(text := (ROOT / "playbooks" / "archive" / "crew-health.yaml").read_text(encoding="utf-8").replace("id: oxygen", "id: heart-rate", 1))
except ValueError:
    pass
else:
    raise AssertionError("duplicate knowledge id was accepted")

# Mission profile, domain metadata, action autonomy and DONKI triggers (playbook v2 fields).
base = (ROOT / "playbooks" / "archive" / "crew-health.yaml").read_text(encoding="utf-8")
assert pb.mission.comm_delay == "real_light_delay" and pb.mission.default_autonomy == "edge_first"
v2 = engine.load_playbook(
    base.replace(
        'start: "2024-05-01T00:00:00Z"',
        'start: "2024-05-01T00:00:00Z"\n  profile: iss_leo\n  duration_days: 180\n  comm_delay: { fixed_seconds: 1 }\n'
        "  magnetosphere_shielding: true\n  default_autonomy: earth_first",
    )
    .replace(
        "    label: Mind and sleep\n",
        "    label: Mind and sleep\n    sources: [daily_checkin]\n    privacy: private\n    horizon: { chronic: weeks }\n",
    )
    .replace("    label: Cabin air\n", "    label: Cabin air\n    shared_by_group: true\n")
    .replace("      - { do: alert_crew }\n      - { do: page_role, role: commander }", "      - { do: alert_crew, scope: all, autonomous: true }\n      - { do: page_role, role: commander }", 1)
    + "  - id: sep_onset\n    domain: radiation\n    metric: dose_rate\n    when: { type: donki, event: sep_onset }\n"
    "    severity: act\n    message: A solar particle event has begun.\n    actions:\n      - { do: log }\n"
)
assert v2.mission.comm_delay.fixed_seconds == 1 and v2.mission.default_autonomy == "earth_first"
assert v2.domains["environment"].shared_by_group and v2.domains["behavioral"].horizon.chronic == "weeks"
# A domain's privacy is the default for indicators that set none; explicit ones win.
assert v2.domains["behavioral"].indicators["mood"].privacy == "private"
v3 = engine.load_playbook(base.replace("    label: Cabin air\n", "    label: Cabin air\n    privacy: private\n"))
assert v3.domains["environment"].indicators["co2"].privacy == "always_shared"
assert any(a.autonomous and a.scope == "all" for r in v2.rules for a in r.actions)
# Readings alone never fire a DONKI rule.
s = engine.new_state()
assert [e["alert"]["rule"] for e in engine.step(v2, s, {"domain": "radiation", "metric": "dose_rate", "value": 1, "ts": 0})] == []
for bad in (
    base.replace('start: "2024-05-01T00:00:00Z"', 'start: "2024-05-01T00:00:00Z"\n  comm_delay: light'),
    base.replace("    label: Cabin air\n", "    label: Cabin air\n    horizon: { acute: fortnights }\n"),
    base.replace("      - { do: alert_crew }", "      - { do: alert_crew, scope: galaxy }", 1),
    base + "  - id: x\n    domain: radiation\n    metric: dose_rate\n    when: { type: donki, event: eclipse }\n    severity: act\n    message: x\n",
):
    try:
        engine.load_playbook(bad)
    except ValueError:
        continue
    raise AssertionError("invalid v2 field was accepted")

# The shipped playbooks validate.
shipped = {}
for name in ("mars-transit", "iss-leo"):
    p = shipped[name] = engine.load_playbook((ROOT / "playbooks" / f"{name}.yaml").read_text(encoding="utf-8"))
    assert p.name == name and p.mission.profile and p.space_weather and p.checkin and p.ai, name

# DONKI events become triggers: SEP onsets at their time, CMEs when their front reaches Mars.
trig = space.triggers(sep + cme + gst)
assert [t["ts"] for t in trig] == sorted(t["ts"] for t in trig)
assert {"event": "sep_onset", "id": sep[0]["id"], "ts": sep[0]["time"]} in trig
assert [t["ts"] for t in trig if t["event"] == "cme_arrival"] == sorted(c["mars_arrival"] for c in cme if c.get("mars_arrival"))
assert not any(t["event"] not in ("sep_onset", "cme_arrival") for t in trig)

# Same SEP, two missions: Mars transit shelters at the edge at once; low Earth orbit sends it to Earth review.
H = 3_600_000
mars, iss = shipped["mars-transit"], shipped["iss-leo"]
s = engine.new_state()
engine.step(mars, s, {"domain": "radiation", "metric": "dose_rate", "value": 0.7, "ts": 0})
fired = engine.donki_step(mars, s, {"event": "sep_onset", "id": "SEP-1", "ts": H})
assert [e["type"] for e in fired] == ["fired"], fired
a = fired[0]["alert"]
assert a["rule"] == "sep_onset" and a["severity"] == "critical" and a["value"] == 0.7 and a["ts"] == H
assert a["checklist"] == "shelter" and a["alert_crew"] == "all" and a["logged"] and "queued" not in a
assert engine.donki_step(mars, s, {"event": "sep_onset", "id": "SEP-1", "ts": H}) == [], "an active DONKI alert fires once"
assert engine.donki_step(mars, s, {"event": "flare", "id": "x", "ts": H}) == []
# It holds for the rule's hold_hours, then the next reading clears it.
hold = next(r.when.hold_hours for r in mars.rules if r.id == "sep_onset")
assert engine.step(mars, s, {"domain": "radiation", "metric": "dose_rate", "value": 2, "ts": H + hold * H - 1}) == []
assert [e["type"] for e in engine.step(mars, s, {"domain": "radiation", "metric": "dose_rate", "value": 1, "ts": H + hold * H})] == ["cleared"]

s = engine.new_state()
a = engine.donki_step(iss, s, {"event": "sep_onset", "id": "SEP-1", "ts": H})[0]["alert"]
assert a["severity"] == "warning" and "checklist" not in a and a["logged"]
assert a["queued"] == [{"do": "notify", "role": "flight_surgeon"}] and "notified" not in a

# Autonomy: an action without `autonomous` follows the mission default; alert_crew scope defaults to the module.
s = engine.new_state()
feed(s, "o2", [15], domain="environment")  # crew-health: no default_autonomy, so edge_first
a = feed(s, "o2", [15], domain="environment", t0=1)[0]["alert"]
assert a["alert_crew"] == "group" and a["paged"] == ["commander"] and "queued" not in a
s = engine.new_state()
for t in (0, 1):
    out = engine.step(v2, s, {"domain": "environment", "metric": "o2", "value": 15, "ts": t})
a = out[0]["alert"]  # v2: earth_first, but alert_crew is marked autonomous: true
assert a["alert_crew"] == "all" and a["queued"] == [{"do": "show_checklist", "checklist": "air_o2"}, {"do": "page_role", "role": "commander"}]

# Sharing: private stays home until shared, shared can be withheld, always_shared cannot. Physical alerts always go.
assert engine.is_shared(pb, {}, "cardiovascular", "heart_rate")
assert not engine.is_shared(pb, {"cardiovascular/heart_rate": False}, "cardiovascular", "heart_rate")
assert not engine.is_shared(pb, {}, "behavioral", "mood")
assert engine.is_shared(pb, {"behavioral/mood": True}, "behavioral", "mood")
assert engine.is_shared(pb, {"environment/co2": False}, "environment", "co2")
assert engine.is_shared(pb, {}, "unknown", "thing")
assert engine.withheld(pb, {}) == ["behavioral/mood", "behavioral/sleep_hours", "behavioral/reaction_time"]
hr = {"domain": "cardiovascular", "metric": "heart_rate", "severity": "act", "ts": 1}
mood = {"domain": "behavioral", "metric": "mood", "severity": "watch", "ts": 2}
st = {"alerts": [hr, mood], "overall": "act", "domains": {"cardiovascular": "act", "behavioral": "watch"},
      "forecasts": [{"domain": "behavioral", "metric": "mood"}], "baselines": {"behavioral/mood": 4, "cardiovascular/heart_rate": 60},
      "learning": ["behavioral/sleep_hours"], "crew_alerts": [{"key": "x"}], "playbook": "p@1"}
rows = [{"domain": "behavioral", "metric": "mood", "value": 2, "ts": 2}, {"domain": "cardiovascular", "metric": "heart_rate", "value": 99, "ts": 2}]
withhold_hr = {"cardiovascular/heart_rate": False}
r, e = engine.for_earth(pb, withhold_hr, rows, st)
assert r == [] and e["alerts"] == [hr] and e["domains"] == {"cardiovascular": "act"} and e["forecasts"] == []
assert e["baselines"] == {} and e["learning"] == [] and "crew_alerts" not in e and e["playbook"] == "p@1"
r, e = engine.for_earth(pb, {"behavioral/mood": True}, rows, st)
assert len(r) == 2 and e["alerts"] == [hr, mood] and e["forecasts"] == st["forecasts"]
assert engine.for_earth(pb, {}, rows, None) == ([rows[1]], None)

# Flight-surgeon-only: a shared private-level indicator reaches the surgeon, not the commander.
shared_mood = {"behavioral/mood": True}
r, e = engine.for_earth(pb, engine.surgeon_only(pb, shared_mood), rows, st)
assert r == [rows[1]] and e["alerts"] == [hr] and e["domains"] == {"cardiovascular": "act"} and e["forecasts"] == []
assert "behavioral/mood" in engine.withheld(pb, engine.surgeon_only(pb, shared_mood))
assert engine.surgeon_only(pb, withhold_hr)["cardiovascular/heart_rate"] is False  # other choices kept
assert engine.surgeon_only(None, shared_mood) == shared_mood
assert engine.alert_open(pb, "cardiovascular", "heart_rate") and not engine.alert_open(pb, "behavioral", "mood")

# Tiger Data history: baselines seeded from daily averages, chronic slopes per day.
mt = engine.load_playbook((ROOT / "playbooks" / "mars-transit.yaml").read_text(encoding="utf-8"))
D = 86_400_000
daily = [{"day": i * D, "domain": "bone", "metric": "bone_density", "avg": 100 - 0.5 * i, "n": 2} for i in range(4)]
daily += [{"day": 0, "domain": "cardiovascular", "metric": "heart_rate", "avg": 60.0, "n": 5}]  # too few samples
s = engine.new_state()
assert engine.seed_baselines(mt, s, daily) == ["bone/bone_density"]
assert s["metrics"]["bone/bone_density"]["learned"] and s["metrics"]["bone/bone_density"]["mean"] == 99.25
assert engine.seed_baselines(mt, s, daily) == []  # never overwrites what this state already knows
c = engine.chronic_trends(mt, daily)
assert list(c) == ["bone/bone_density"] and abs(c["bone/bone_density"]["per_day"] + 0.5) < 1e-9  # heart: no chronic horizon
assert engine.chronic_trends(mt, daily[:2]) == {}  # under CHRONIC_MIN_DAYS

print("engine ok")

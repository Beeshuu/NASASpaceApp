"""Playbook engine: schema, personal baselines, rule evaluation.

Pure Python with no Workers imports, so it runs under plain CPython for tests.
Nothing in here names a domain, metric or severity. Those come from the playbook.
"""

import math
from datetime import datetime
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo in a playbook is an error, not a silent no-op


class IndicatorSpec(Strict):
    label: str
    unit: str | None = None
    note: str | None = None  # shown under the label, e.g. where the value comes from
    privacy: Literal["private", "shared", "always_shared"] = "shared"
    baseline: bool = True  # false for running totals, where "versus your usual" means nothing
    baseline_samples: int | None = Field(default=None, ge=1)


class Horizon(Strict):
    """How fast this domain changes: acute for minutes-to-days events, chronic for slow trends."""

    acute: Literal["minutes", "hours", "days"] | None = None
    chronic: Literal["days", "weeks", "months"] | None = None


class Domain(Strict):
    label: str
    indicators: dict[str, IndicatorSpec]
    sources: list[str] = []  # where readings come from, e.g. wearable, cabin_sensor, donki_events
    privacy: Literal["private", "shared", "always_shared"] | None = None  # default for indicators that set none
    horizon: Horizon | None = None
    shared_by_group: bool = False  # one reading stands for everyone in the same module, e.g. cabin air


class Severity(Strict):
    id: str
    label: str


class Threshold(Strict):
    type: Literal["threshold"]
    op: Literal[">", ">=", "<", "<="]
    value: float


class Drift(Strict):
    """Change against the personal baseline. `value` is acute (this reading), `trend` is chronic (slow average)."""

    type: Literal["drift"]
    of: Literal["value", "trend"] = "value"
    direction: Literal["above", "below", "either"]
    percent: float = Field(gt=0)


class Forecast(Strict):
    """The digital twin: fires when the smoothed trend is on course to cross `value` within the horizon."""

    type: Literal["forecast"]
    op: Literal[">=", "<="]
    value: float
    horizon_hours: float = Field(gt=0)


class Donki(Strict):
    """A NASA DONKI space weather event, not a reading. Fired by donki_step(), cleared by a reading after hold_hours."""

    type: Literal["donki"]
    event: Literal["sep_onset", "cme_arrival"]
    hold_hours: float = Field(default=24, gt=0)  # how long the alert stays active after the event


class Action(Strict):
    do: str
    checklist: str | None = None
    role: str | None = None
    autonomous: bool | None = None  # true: the edge acts without waiting for Earth; unset: mission default_autonomy
    scope: Literal["self", "group", "all"] | None = None  # who alert_crew reaches


class Rule(Strict):
    id: str
    domain: str
    metric: str
    when: Annotated[Threshold | Drift | Forecast | Donki, Field(discriminator="type")]
    severity: str
    sustain: int = Field(default=1, ge=1)  # consecutive readings that must match before it fires
    message: str
    actions: list[Action] = []


class Checklist(Strict):
    title: str
    steps: list[str] = Field(min_length=1)


class CheckinField(Strict):
    """One question in the daily check-in. Every kind except `text` becomes a reading for its indicator."""

    id: str
    kind: Literal["scale", "number", "reaction_test", "text"]
    question: str
    domain: str | None = None
    metric: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = Field(default=None, gt=0)
    low_label: str | None = None
    high_label: str | None = None


class Checkin(Strict):
    title: str
    fields: list[CheckinField] = Field(min_length=1)


class Baseline(Strict):
    samples: int = Field(default=20, ge=1)
    trend_alpha: float = Field(default=0.1, gt=0, le=1)


class Twin(Strict):
    """Holt double exponential smoothing: a level and a slope per forecast indicator."""

    # Smoothing time constant as a share of the rule's horizon: a 100-day forecast reads the trend
    # over days, a 30-minute one over minutes. Sensor rounding at fine sampling cannot swing it.
    horizon_fraction: float = Field(default=0.05, gt=0, le=1)
    min_samples: int = Field(default=5, ge=2)  # readings before a forecast is trusted


class Ai(Strict):
    """The assistant that explains alerts. It explains, guides and escalates. It never diagnoses."""

    role: str  # the name the crew sees
    model: str
    embedding_model: str
    prompt: str  # system prompt
    max_tokens: int = Field(default=400, ge=50, le=2000)
    top_k: int = Field(default=3, ge=1, le=10)  # guidance documents retrieved per question
    min_score: float = Field(default=0.6, ge=0, le=1)  # cosine similarity below this is not used
    score_margin: float = Field(default=0.08, ge=0, le=1)  # and a document must be this close to the best match


class KnowledgeDoc(Strict):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    title: str
    text: str = Field(max_length=1500)  # the embedding model reads about 512 tokens


class IndicatorRef(Strict):
    domain: str
    metric: str


class DoseModel(Strict):
    """Parameters of the crew dose modeled from space weather events. Illustrative, not dosimetry."""

    quiet_rate: float = Field(gt=0)  # mSv/day with no event in progress
    sep_peak: float = Field(ge=0)  # mSv/day at the start of a particle event linked to an X1 flare
    unlinked_flare_factor: float = Field(default=0.5, ge=0)  # used when no flare is linked to the event
    sep_decay_hours: float = Field(gt=0)
    shock_peak: float = Field(ge=0)  # mSv/day when a 1000 km/s CME front arrives
    shock_hours: float = Field(gt=0)


class SpaceWeather(Strict):
    """Which indicators receive the dose modeled from space weather events, and the model's parameters."""

    dose_rate: IndicatorRef
    cumulative_dose: IndicatorRef
    model: DoseModel


class FixedDelay(Strict):
    fixed_seconds: int = Field(ge=0, le=1500)


class Mission(Strict):
    start: datetime  # lets the dashboards say "mission day 212"
    profile: str | None = None  # e.g. mars_transit, iss_leo
    duration_days: int | None = Field(default=None, ge=1)
    # real_light_delay: from the Earth-Mars distance on the mission date.
    comm_delay: Literal["real_light_delay"] | FixedDelay = "real_light_delay"
    magnetosphere_shielding: bool = False  # Earth's field shields low orbit from most solar particles
    default_autonomy: Literal["edge_first", "earth_first"] = "edge_first"  # for actions that do not set autonomous


# Named action handlers, registered once. Each one records its effect on the alert;
# the Durable Object carries out the I/O (store, push to sockets) from that record.
HANDLERS = {}


def action(name):
    def register(fn):
        HANDLERS[name] = fn
        return fn

    return register


@action("show_checklist")
def _show_checklist(alert, a):
    alert["checklist"] = a.checklist


@action("alert_crew")
def _alert_crew(alert, a):
    alert["alert_crew"] = a.scope or "group"  # who else hears it: self, group (same module) or all


@action("page_role")
def _page_role(alert, a):
    alert.setdefault("paged", []).append(a.role)


@action("notify")
def _notify(alert, a):
    alert.setdefault("notified", []).append(a.role)


@action("log")
def _log(alert, a):
    alert["logged"] = True


class Playbook(Strict):
    name: str = Field(pattern=r"^[a-z0-9-]+$")
    version: int = Field(ge=1)
    title: str
    severities: list[Severity] = Field(min_length=1)  # lowest to highest
    baseline: Baseline = Baseline()
    twin: Twin = Twin()
    mission: Mission | None = None
    space_weather: SpaceWeather | None = None
    ai: Ai | None = None
    knowledge: list[KnowledgeDoc] = []
    domains: dict[str, Domain]
    checklists: dict[str, Checklist] = {}
    checkin: Checkin | None = None
    rules: list[Rule] = []

    @model_validator(mode="after")
    def _references_resolve(self):
        severities = {s.id for s in self.severities}
        ids = [d.id for d in self.knowledge]
        assert len(ids) == len(set(ids)), "knowledge: duplicate id"
        for d in self.domains.values():
            for spec in d.indicators.values():
                if d.privacy and "privacy" not in spec.model_fields_set:
                    spec.privacy = d.privacy
        if self.space_weather:
            for ref in (self.space_weather.dose_rate, self.space_weather.cumulative_dose):
                assert ref.domain in self.domains, f"space_weather: unknown domain {ref.domain!r}"
                assert ref.metric in self.domains[ref.domain].indicators, f"space_weather: unknown metric {ref.metric!r}"
        seen = set()
        for f in self.checkin.fields if self.checkin else []:
            where = f"check-in field {f.id!r}"
            assert f.id not in seen, f"{where}: duplicate id"
            seen.add(f.id)
            if f.kind != "text":
                assert f.domain in self.domains, f"{where}: unknown domain {f.domain!r}"
                assert f.metric in self.domains[f.domain].indicators, f"{where}: unknown metric {f.metric!r}"
                assert f.min is not None and f.max is not None and f.min < f.max, f"{where}: needs min below max"
        seen = set()
        for r in self.rules:
            where = f"rule {r.id!r}"
            assert r.id not in seen, f"{where}: duplicate id"
            seen.add(r.id)
            assert r.domain in self.domains, f"{where}: unknown domain {r.domain!r}"
            assert r.metric in self.domains[r.domain].indicators, f"{where}: unknown metric {r.metric!r}"
            assert r.severity in severities, f"{where}: unknown severity {r.severity!r}"
            if r.when.type == "drift":
                assert self.domains[r.domain].indicators[r.metric].baseline, f"{where}: drift needs a baseline, but {r.metric!r} has baseline: false"
            for a in r.actions:
                assert a.do in HANDLERS, f"{where}: unknown action {a.do!r}"
                if a.do == "show_checklist":
                    assert a.checklist in self.checklists, f"{where}: unknown checklist {a.checklist!r}"
                if a.do in ("page_role", "notify"):
                    assert a.role, f"{where}: {a.do} needs a role"
        return self


def load_playbook(text: str) -> Playbook:
    """Parse and validate playbook YAML. Raises ValueError (pydantic) with every problem found."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"not valid YAML: {e}") from None
    return Playbook.model_validate(data)


def checkin_readings(pb: Playbook, answers: dict) -> tuple[list[dict], dict]:
    """Validate check-in answers against the playbook. Returns (readings without ts, answers to store)."""
    readings, kept = [], {}
    for f in pb.checkin.fields:
        v = answers.get(f.id)
        if f.kind == "text":
            if v:
                kept[f.id] = str(v)[:1000]
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"{f.id}: a number is required")
        if not f.min <= v <= f.max:
            raise ValueError(f"{f.id}: must be between {f.min:g} and {f.max:g}")
        kept[f.id] = v
        readings.append(
            {
                "domain": f.domain,
                "metric": f.metric,
                "value": v,
                "unit": pb.domains[f.domain].indicators[f.metric].unit,
                "source": "self_test" if f.kind == "reaction_test" else "self_report",
            }
        )
    return readings, kept


def explain_prompt(pb: Playbook, st: dict | None, alert: dict | None, question: str | None, docs: list) -> str:
    """The user message for the assistant: only what the playbook and the crew member's own state provide."""
    lines = []
    if question:
        lines.append(f"Crew member's question: {question}")
    if alert:
        spec = pb.domains[alert["domain"]].indicators[alert["metric"]]
        severity = next(s.label for s in pb.severities if s.id == alert["severity"])
        reading = f'{spec.label} is {alert["value"]:g}{" " + spec.unit if spec.unit else ""}'
        if alert.get("baseline") is not None:
            reading += f', their usual is {alert["baseline"]:g}'
        lines += [f'Active alert ({severity}): {alert["message"]}', f"Reading: {reading}."]
        checklist = pb.checklists.get(alert.get("checklist"))
        if checklist:
            steps = " ".join(f"{i}. {s}" for i, s in enumerate(checklist.steps, 1))
            lines.append(f'Playbook checklist "{checklist.title}": {steps}')
    others = [a["message"] for a in (st or {}).get("alerts", []) if a is not alert]
    if others:
        lines.append("Other active alerts: " + " ".join(others))
    if not alert and not others:
        lines.append("No alert is active for this crew member.")
    if not (alert and pb.checklists.get(alert.get("checklist"))):
        lines.append("No playbook checklist applies here.")
    if not docs:
        lines.append("No guidance document covers this.")
    for d in docs:
        lines.append(f"Guidance [{d.title}]: {d.text.strip()}")
    return "\n".join(lines)


def new_state():
    return {"metrics": {}, "rules": {}}


HISTORY = 60  # points kept per forecast indicator for the twin chart


def _twin_update(m, value, ts, tau):
    """Advance one indicator's twin. `tau` is the smoothing time constant in ms."""
    if "level" not in m:
        m.update(level=value, slope=0.0, t=ts, fn=1)
    elif ts > m["t"]:
        dt = ts - m["t"]
        a = 1 - math.exp(-dt / tau)  # weight by elapsed time, so the sampling rate does not change the answer
        b = 1 - math.exp(-dt / (2 * tau))
        prev = m["level"]
        m["level"] = a * value + (1 - a) * (prev + m["slope"] * dt)
        m["slope"] = b * (m["level"] - prev) / dt + (1 - b) * m["slope"]  # per millisecond
        m["t"] = ts
        m["fn"] += 1
    pts = m.setdefault("pts", [])
    gap = m.setdefault("gap", 0)
    if not pts or ts - pts[-1][0] >= gap:
        pts.append([ts, value])
    if len(pts) > HISTORY:
        # Halve the resolution instead of dropping the past, so the chart always spans the whole record.
        m["pts"] = pts[::2]
        m["gap"] = max(1, gap * 2, (pts[-1][0] - pts[0][0]) // HISTORY)


def crossing(when, m, min_samples):
    """When the twin expects the threshold to be crossed: an epoch ms, or None if not within the horizon."""
    if m.get("fn", 0) < min_samples:
        return None
    gap, slope = when.value - m["level"], m["slope"]
    if when.op == "<=":
        gap, slope = -gap, -slope
    if gap <= 0:
        return m["t"]
    if slope <= 0:
        return None
    eta = m["t"] + gap / slope
    return round(eta) if eta - m["t"] <= when.horizon_hours * 3_600_000 else None


# ---- Long-term history from Tiger Data: daily averages, [{day, domain, metric, avg, n}] ----

CHRONIC_MIN_DAYS = 3  # daily averages before a chronic trend means anything


def seed_baselines(pb: Playbook, state: dict, daily: list[dict]) -> list[str]:
    """Indicators with no readings yet in this state start from their history instead of learning from zero.

    The baseline is the mean of the daily averages, weighted by readings. Returns the keys it seeded.
    """
    sums = {}
    for row in daily:
        k = f'{row["domain"]}/{row["metric"]}'
        tot, n = sums.get(k, (0.0, 0))
        sums[k] = (tot + row["avg"] * row["n"], n + row["n"])
    seeded = []
    for k, (tot, n) in sums.items():
        d, i = k.split("/", 1)
        spec = pb.domains.get(d) and pb.domains[d].indicators.get(i)
        if not spec or not spec.baseline or n < (spec.baseline_samples or pb.baseline.samples) or k in state["metrics"]:
            continue
        mean = tot / n
        state["metrics"][k] = {"n": n, "mean": mean, "trend": mean, "learned": True, "seeded": True}
        seeded.append(k)
    return seeded


def chronic_trends(pb: Playbook, daily: list[dict]) -> dict:
    """Least-squares slope per day of the daily averages, for indicators in domains with a chronic horizon."""
    series = {}
    for row in daily:
        dom = pb.domains.get(row["domain"])
        if dom and dom.horizon and dom.horizon.chronic and row["metric"] in dom.indicators:
            series.setdefault(f'{row["domain"]}/{row["metric"]}', []).append((row["day"] / 86_400_000, row["avg"]))
    out = {}
    for k, pts in series.items():
        if len(pts) < CHRONIC_MIN_DAYS:
            continue
        mx = sum(x for x, _ in pts) / len(pts)
        my = sum(y for _, y in pts) / len(pts)
        var = sum((x - mx) ** 2 for x, _ in pts)
        slope = sum((x - mx) * (y - my) for x, y in pts) / var if var else 0.0
        out[k] = {"per_day": slope, "days": len(pts), "mean": my}
    return out


def _matches(when, value, m):
    if when.type == "threshold":
        return {">": value > when.value, ">=": value >= when.value, "<": value < when.value, "<=": value <= when.value}[when.op]
    if not m["learned"] or m["mean"] == 0:  # no baseline yet, or percent of zero is undefined
        return False
    pct = ((value if when.of == "value" else m["trend"]) - m["mean"]) / abs(m["mean"]) * 100
    if when.direction == "above":
        return pct >= when.percent
    if when.direction == "below":
        return pct <= -when.percent
    return abs(pct) >= when.percent


def step(pb: Playbook, state: dict, r: dict) -> list[dict]:
    """Feed one reading {domain, metric, value, ts}. Updates state in place, returns fired and cleared events."""
    domain = pb.domains.get(r["domain"])
    spec = domain and domain.indicators.get(r["metric"])
    if not spec:
        return []  # not in the playbook: still displayed, never judged

    key = f'{r["domain"]}/{r["metric"]}'
    value = r["value"]
    m = state["metrics"].setdefault(key, {"n": 0, "mean": 0.0, "trend": value, "learned": False})
    if spec.baseline and not m["learned"]:
        # Personal baseline: mean of the first N readings, then frozen so slow drift stays visible.
        m["n"] += 1
        m["mean"] += (value - m["mean"]) / m["n"]
        m["learned"] = m["n"] >= (spec.baseline_samples or pb.baseline.samples)
    m["trend"] += pb.baseline.trend_alpha * (value - m["trend"])
    m["last"] = value
    mine = [rule for rule in pb.rules if rule.domain == r["domain"] and rule.metric == r["metric"]]
    horizon = next((rule.when.horizon_hours for rule in mine if rule.when.type == "forecast"), None)
    if horizon:
        _twin_update(m, value, r["ts"], horizon * 3_600_000 * pb.twin.horizon_fraction)

    events = []
    for rule in mine:
        if rule.when.type == "donki":
            # Fired by donki_step(). A reading after the hold time clears it.
            rs = state["rules"].get(rule.id, {})
            if rs.get("active") and r["ts"] >= rs["alert"]["ts"] + rule.when.hold_hours * 3_600_000:
                rs["active"] = False
                events.append({"type": "cleared", "alert": rs.pop("alert"), "ts": r["ts"]})
            continue
        rs = state["rules"].setdefault(rule.id, {"streak": 0, "active": False})
        eta = crossing(rule.when, m, pb.twin.min_samples) if rule.when.type == "forecast" else None
        hit = eta is not None if rule.when.type == "forecast" else _matches(rule.when, value, m)
        if hit and rs["active"] and eta is not None:
            rs["alert"]["eta"] = eta  # the forecast moves with every reading
        rs["streak"] = rs["streak"] + 1 if hit else 0
        if hit and not rs["active"] and rs["streak"] >= rule.sustain:
            events.append(_fire(pb, rule, rs, value, m["mean"] if m["learned"] else None, r["ts"], eta))
        elif not hit and rs["active"]:
            rs["active"] = False
            events.append({"type": "cleared", "alert": rs.pop("alert"), "ts": r["ts"]})
    return events


def donki_step(pb: Playbook, state: dict, t: dict) -> list[dict]:
    """Feed one DONKI trigger {event, id, ts} (see space.triggers). Fires the donki rules for that event."""
    events = []
    for rule in pb.rules:
        if rule.when.type == "donki" and rule.when.event == t["event"]:
            rs = state["rules"].setdefault(rule.id, {"streak": 0, "active": False})
            if not rs["active"]:
                m = state["metrics"].get(f"{rule.domain}/{rule.metric}", {})
                events.append(_fire(pb, rule, rs, m.get("last", 0.0), None, t["ts"], None, donki=t["id"]))
    return events


def _fire(pb, rule, rs, value, baseline, ts, eta, donki=None):
    alert = {
        "id": f"{rule.id}:{ts}",
        "rule": rule.id,
        "domain": rule.domain,
        "metric": rule.metric,
        "severity": rule.severity,
        "message": rule.message,
        "value": value,
        "baseline": baseline,
        "ts": ts,
    }
    if eta is not None:
        alert["eta"] = eta
    if donki:
        alert["donki"] = donki  # the DONKI event id that fired it
    edge_first = not pb.mission or pb.mission.default_autonomy == "edge_first"
    for a in rule.actions:
        # Logging is never held back. Anything else runs at the edge now, or waits for Earth review.
        if a.do == "log" or (a.autonomous if a.autonomous is not None else edge_first):
            HANDLERS[a.do](alert, a)
        else:
            alert.setdefault("queued", []).append(a.model_dump(exclude_none=True, exclude={"autonomous"}))
    rs.update(active=True, alert=alert, streak=rs.get("streak", 0))
    return {"type": "fired", "alert": alert}


def status(pb: Playbook, state: dict) -> dict:
    """What the dashboards need: active alerts, worst severity per domain and overall, learned baselines."""
    rank = {s.id: i for i, s in enumerate(pb.severities)}
    alerts = [state["rules"][r.id]["alert"] for r in pb.rules if state["rules"].get(r.id, {}).get("active")]
    alerts.sort(key=lambda a: (-rank[a["severity"]], a["ts"]))
    # One alert per indicator: when a watch rule and an act rule both match, only the worse one is shown.
    worst = {}
    for a in alerts:
        worst.setdefault((a["domain"], a["metric"]), a)
    alerts = list(worst.values())
    domains = {}
    for a in reversed(alerts):  # worst last, so it wins
        domains[a["domain"]] = a["severity"]
    watched = {f"{r.domain}/{r.metric}" for r in pb.rules if r.when.type == "drift"}
    metrics = state["metrics"]
    compared = {f"{d}/{i}" for d, dom in pb.domains.items() for i, spec in dom.indicators.items() if spec.baseline}
    forecasts = []
    for r in pb.rules:
        m = metrics.get(f"{r.domain}/{r.metric}", {})
        if r.when.type == "forecast" and m.get("pts"):
            forecasts.append(
                {
                    "rule": r.id,
                    "domain": r.domain,
                    "metric": r.metric,
                    "op": r.when.op,
                    "threshold": r.when.value,
                    "horizon_ms": r.when.horizon_hours * 3_600_000,
                    "level": m["level"],
                    "slope": m["slope"],
                    "t": m["t"],
                    "eta": crossing(r.when, m, pb.twin.min_samples),
                    "points": m["pts"],
                    # The slow trend from months of daily averages (Tiger Data), next to the twin's fast slope.
                    "chronic": state.get("chronic", {}).get(f"{r.domain}/{r.metric}"),
                }
            )
    return {
        "playbook": f"{pb.name}@{pb.version}",
        "forecasts": forecasts,
        "overall": alerts[0]["severity"] if alerts else None,
        "domains": domains,
        "alerts": alerts,
        "baselines": {k: m["mean"] for k, m in metrics.items() if m["learned"] and k in compared},
        "learning": sorted(k for k in watched if not metrics.get(k, {}).get("learned")),
        "chronic": state.get("chronic", {}),
    }


# ---- Sharing: what Earth may see ----
# private: the crew member must share it. shared: sent unless withheld. always_shared: cannot be withheld.


def privacy(pb: Playbook | None, domain: str, metric: str) -> str:
    """An indicator's privacy level. Anything the playbook does not name counts as shared."""
    spec = pb.domains.get(domain).indicators.get(metric) if pb and domain in pb.domains else None
    return spec.privacy if spec else "shared"


def is_shared(pb: Playbook | None, choices: dict, domain: str, metric: str) -> bool:
    """Are this indicator's readings sent to Earth? `choices` maps "domain/metric" to the crew member's choice."""
    level = privacy(pb, domain, metric)
    return level == "always_shared" or choices.get(f"{domain}/{metric}", level == "shared")


def alert_shared(pb: Playbook | None, choices: dict, domain: str, metric: str) -> bool:
    """Physical alerts always reach Earth, even when the readings are withheld. Private ones only once shared."""
    return privacy(pb, domain, metric) != "private" or is_shared(pb, choices, domain, metric)


def alert_open(pb: Playbook | None, domain: str, metric: str) -> bool:
    """May the black box show this alert's content to all of mission control? Never for private-level indicators:
    sharing them opens them to the flight surgeon only, not to the commander reading the log."""
    return privacy(pb, domain, metric) != "private"


def surgeon_only(pb: Playbook | None, choices: dict) -> dict:
    """`choices` with every private-level indicator withheld: what Earth shows anyone but the flight surgeon."""
    if not pb:
        return choices
    hide = {f"{d}/{i}": False for d, dom in pb.domains.items() for i, spec in dom.indicators.items() if spec.privacy == "private"}
    return {**choices, **hide}


def for_earth(pb: Playbook | None, choices: dict, readings: list[dict], status: dict | None) -> tuple[list[dict], dict | None]:
    """Earth's copy of one update: only what the crew member shares, plus every physical alert."""
    readings = [r for r in readings if is_shared(pb, choices, r["domain"], r["metric"])]
    if not status:
        return readings, status
    alerts = [a for a in status["alerts"] if alert_shared(pb, choices, a["domain"], a["metric"])]
    domains = {}
    for a in reversed(alerts):  # worst last, so it wins
        domains[a["domain"]] = a["severity"]
    shared = lambda key: is_shared(pb, choices, *key.split("/", 1))  # noqa: E731
    return readings, {
        **{k: v for k, v in status.items() if k != "crew_alerts"},  # other crew members' alerts reach Earth from them
        "alerts": alerts,
        "overall": alerts[0]["severity"] if alerts else None,
        "domains": domains,
        "forecasts": [f for f in status["forecasts"] if is_shared(pb, choices, f["domain"], f["metric"])],
        "baselines": {k: v for k, v in status["baselines"].items() if shared(k)},
        "learning": [k for k in status["learning"] if shared(k)],
        "chronic": {k: v for k, v in status.get("chronic", {}).items() if shared(k)},
    }


def withheld(pb: Playbook | None, choices: dict) -> list[str]:
    """"domain/metric" of every playbook indicator Earth does not receive."""
    if not pb:
        return []
    return [f"{d}/{i}" for d, dom in pb.domains.items() for i in dom.indicators if not is_shared(pb, choices, d, i)]

import asyncio
import calendar
import hashlib
import hmac
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from js import Object, Request as JsRequest, Uint8Array, WebSocketPair, crypto
from pyodide.ffi import to_js
from workers import DurableObject, Response, WorkerEntrypoint, WorkflowEntrypoint, asgi, fetch

import auth
import crew_sim
import engine
import ledger
import report
import space

BINDINGS = ["ASTRONAUT", "LEDGER", "DB", "BUCKET", "INDICATORS", "AI", "VECTORIZE", "ASSETS", "INCIDENT", "TIGER"]

# ---- Who is calling: Cloudflare Access in front, Auth0 behind it (PROGRESS.md, phase 13) ----

_jwks = {"at": 0.0, "keys": {}}


def u8(b: bytes):
    arr = Uint8Array.new(len(b))
    arr.assign(b)
    return arr


async def access_key(env, kid):
    """The Access team's public key `kid`. Refetched hourly, and at most once a minute for a kid not seen yet (rotation)."""
    c = _jwks
    age = time.time() - c["at"]
    if age > 3600 or (kid not in c["keys"] and age > 60):
        res = await fetch(f"{str(env.ACCESS_TEAM_DOMAIN).rstrip('/')}/cdn-cgi/access/certs")
        if res.status == 200:
            alg = to_js({"name": "RSASSA-PKCS1-v1_5", "hash": "SHA-256"}, dict_converter=Object.fromEntries)
            keys = {}
            for jwk in json.loads(await res.text())["keys"]:
                keys[jwk["kid"]] = await crypto.subtle.importKey("jwk", to_js(jwk, dict_converter=Object.fromEntries), alg, False, to_js(["verify"]))
            c.update(at=time.time(), keys=keys)
        else:
            print(f"Access certs: HTTP {res.status}")
    return c["keys"].get(kid)


def guest(headers):
    """The guest identity in the role and as the crew member picked on the demo page, which keeps both in cookies."""
    cookies = headers.get("cookie")
    return auth.guest_identity(auth.cookie(cookies, "vop_role"), auth.cookie(cookies, "vop_crew"), crew_sim.CREW)


async def authenticate(env, headers):
    """The caller's identity (auth.identity) from the Access JWT. Raises ValueError when there is none.

    `headers`: anything with .get(name), a Starlette or a JS Headers object. Without ACCESS_AUD only local
    development gets in, as the DEV_ROLE identity, and only from loopback: deployed, that fails closed.
    """
    # The guest hostname has no Access application: anyone reaching it is a guest. Demo mode only, where the data
    # is the scripted replay, never a real crew member's.
    if demo_mode(env) and auth.is_guest_host(headers.get("host"), getattr(env, "GUEST_HOST", None)):
        return guest(headers)
    aud = str(getattr(env, "ACCESS_AUD", None) or "")
    if not aud:
        role = getattr(env, "DEV_ROLE", None)
        # wrangler dev rewrites the URL to the route's host, so the client IP tells local from deployed.
        # Cloudflare sets CF-Connecting-IP to the real client, which is never loopback.
        if role and headers.get("cf-connecting-ip") in ("127.0.0.1", "::1"):
            if str(role) == "guest" and demo_mode(env):  # the guest page, run locally
                return guest(headers)
            return auth.dev_identity(str(role), getattr(env, "DEV_CREW_ID", None))
        raise ValueError("sign-in is not configured on this Worker")
    # The header is what Access guarantees. The cookie is the fallback the browser sends on the same origin.
    token = headers.get("cf-access-jwt-assertion") or auth.cookie(headers.get("cookie"), "CF_Authorization")
    if not token:
        raise ValueError("not signed in")
    header, payload, signed, sig = auth.split(token)
    key = await access_key(env, header.get("kid"))
    if not key or not await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, u8(sig), u8(signed)):
        raise ValueError("bad token signature")
    return auth.identity(payload, str(env.ACCESS_TEAM_DOMAIN), aud, time.time())


async def signed_in(request: Request):
    """Runs before every route: no identity, no answer."""
    try:
        request.state.who = await authenticate(request.scope["env"], request.headers)
    except ValueError as e:
        raise HTTPException(401, str(e)) from None


def need_role(request, *roles):
    who = request.state.who
    if who["role"] not in roles:
        raise HTTPException(403, f"this needs the {' or '.join(roles)} role")
    return who


def no_guest(request):
    """Guests run the demo; they do not upload playbooks or change mission settings for everyone."""
    if request.state.who.get("guest"):
        raise HTTPException(403, "sign in to change this; guests can run the demo")


def need_crew(request, entity_id):
    """Private crew data: only that crew member, or the commander acting as the simulated crew in demo mode."""
    who = request.state.who
    if not auth.acts_as(who, entity_id, crew_sim.CREW if demo_mode(request.scope["env"]) else ()):
        raise HTTPException(403, "only that crew member can see or change this")
    return who


def need_earth(request, entity_id):
    """Earth's delayed, shared-only copy: mission control, or the crew member it is about."""
    return request.state.who if request.state.who["role"] in auth.MISSION else need_crew(request, entity_id)


app = FastAPI(title="Vital Orbit Pulse", dependencies=[Depends(signed_in)])


@app.get("/api/me")
async def me(request: Request):
    env = request.scope["env"]
    who = request.state.who
    return {**who, "guest": bool(who.get("guest")), "demo": demo_mode(env),
            "logout_url": None if who.get("guest") else auth0_logout_url(env, request)}  # fmt: skip


def auth0_logout_url(env, request):
    """Auth0's own logout. Ending only the Access app session leaves Auth0 and the global Access session signed in."""
    domain, client = getattr(env, "AUTH0_DOMAIN", None), getattr(env, "AUTH0_CLIENT_ID", None)
    if not domain or not client:
        return None
    # Then the team domain's logout, which ends the global Access session. Without it Access silently issues a new
    # app token. Must be one of the Auth0 app's Allowed Logout URLs.
    back = f"{str(env.ACCESS_TEAM_DOMAIN).rstrip('/')}/cdn-cgi/access/logout" if getattr(env, "ACCESS_AUD", None) else f"https://{request.url.hostname}"
    return f"https://{domain}/v2/logout?{urlencode({'client_id': client, 'returnTo': back})}"


@app.get("/api/health")
async def health(request: Request):
    env = request.scope["env"]
    return {"ok": True, "bindings": {b: bool(getattr(env, b, None)) for b in BINDINGS}}


@app.get("/api/imports")
async def imports():
    """Phase 1 check: every backend package imports inside the Workers runtime."""
    import fastapi
    import pydantic
    import yaml

    class Probe(pydantic.BaseModel):
        value: float

    parsed = Probe(**yaml.safe_load("value: 1.5"))
    return {
        "fastapi": fastapi.__version__,
        "pydantic": pydantic.__version__,
        "pyyaml": yaml.__version__,
        "roundtrip": parsed.value,
    }


@app.get("/api/astronauts/{entity_id}/ping")
async def ping(entity_id: str, request: Request):
    need_role(request, "commander")
    stub = request.scope["env"].ASTRONAUT.getByName(entity_id)
    return {"entity_id": entity_id, "pings": await stub.ping()}


class Indicator(BaseModel):
    """The one shape every dataset is normalized into."""

    entity_id: str = Field(min_length=1, max_length=64)
    timestamp: datetime
    domain: str = Field(min_length=1, max_length=64)
    metric: str = Field(min_length=1, max_length=64)
    value: float
    unit: str | None = None
    source: str | None = None
    meta: dict | None = None


def require_key(env, given):
    key = getattr(env, "INGEST_KEY", None)
    if not key or not hmac.compare_digest(given, str(key)):
        raise HTTPException(401, "bad ingest key")


_playbook_cache = {"at": 0.0, "sha": None, "pb": None}


async def active_playbook(env):
    """The active playbook, or None. Re-checked against D1 at most every 30 s per isolate."""
    c = _playbook_cache
    if time.time() - c["at"] < 30:
        return c["pb"]
    row = await env.DB.prepare("SELECT sha256, r2_key FROM playbooks WHERE active = 1").first()
    if not row:
        c.update(sha=None, pb=None)
    elif row["sha256"] != c["sha"]:
        obj = await env.BUCKET.get(row["r2_key"])
        try:
            c.update(sha=row["sha256"], pb=engine.load_playbook(await obj.text()))
        except ValueError as e:
            # A stored playbook can stop validating after an engine upgrade. Readings must keep flowing
            # unchecked rather than every request failing, so this counts as no active playbook.
            print(f"active playbook {row['r2_key']} no longer validates: {e}")
            c.update(sha=row["sha256"], pb=None)
    c["at"] = time.time()
    return c["pb"]


@app.put("/api/playbook", status_code=201)
async def put_playbook(request: Request):
    """Validate a playbook, store it in R2, record the version in D1 and make it active."""
    env = request.scope["env"]
    who = need_role(request, "commander")
    no_guest(request)
    body = await request.body()
    if len(body) > 256_000:
        raise HTTPException(413, "playbook is larger than 256 KB")
    text = body.decode()
    try:
        pb = engine.load_playbook(text)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    sha = hashlib.sha256(body).hexdigest()
    db = env.DB
    existing = await db.prepare("SELECT sha256 FROM playbooks WHERE name = ? AND version = ?").bind(pb.name, pb.version).first()
    if existing and existing["sha256"] != sha:
        raise HTTPException(409, f"{pb.name} version {pb.version} already exists with different content. Raise the version number.")

    r2_key = f"playbooks/{pb.name}/v{pb.version}.yaml"
    await env.BUCKET.put(r2_key, text)
    was = await db.prepare("SELECT name, version, sha256 FROM playbooks WHERE active = 1").first()
    await db.batch(
        [
            db.prepare("UPDATE playbooks SET active = 0"),
            db.prepare(
                "INSERT INTO playbooks (name, version, sha256, r2_key, active, created_at) VALUES (?, ?, ?, ?, 1, ?) "
                "ON CONFLICT (name, version) DO UPDATE SET active = 1"
            ).bind(pb.name, pb.version, sha, r2_key, int(time.time() * 1000)),
        ]
    )
    await log_switch(env, was, pb.name, pb.version, sha, who["actor"])
    return {"name": pb.name, "version": pb.version, "sha256": sha, "active": True, "knowledge": await index_knowledge(env, pb)}


async def log_switch(env, was, name, version, sha, actor):
    """After the active row changed in D1: drop the cached playbook and record the switch in the black box."""
    _playbook_cache["at"] = 0  # so the ledger entry carries the new playbook's hash
    if not was or was["sha256"] != sha:
        old = f'{was["name"]}@{was["version"]}' if was else None
        await ledger_log(
            env, "playbook_switch", f"Active playbook changed from {old or 'none'} to {name}@{version}.",
            {"from": old, "from_hash": was["sha256"] if was else None, "to": f"{name}@{version}", "to_hash": sha}, actor=actor,
        )  # fmt: skip


@app.get("/api/playbooks")
async def list_playbooks(request: Request):
    """Stored versions the switcher offers. Deprecated ones stay in R2 and D1 but are not listed."""
    res = await (
        request.scope["env"]
        .DB.prepare("SELECT name, version, sha256, active, created_at FROM playbooks WHERE deprecated = 0 ORDER BY name, version DESC")
        .all()
    )
    return res["results"]


class Activate(BaseModel):
    name: str = Field(max_length=64)
    version: int = Field(ge=1)


@app.post("/api/playbook/activate")
async def activate_playbook(body: Activate, request: Request):
    """Make a stored version active without uploading it again."""
    env = request.scope["env"]
    who = need_role(request, "commander")
    db = env.DB
    row = await db.prepare("SELECT sha256, r2_key, deprecated FROM playbooks WHERE name = ? AND version = ?").bind(body.name, body.version).first()
    if not row:
        raise HTTPException(404, "no such playbook version")
    if row["deprecated"]:
        raise HTTPException(409, "this version is deprecated")
    obj = await env.BUCKET.get(row["r2_key"])
    try:
        engine.load_playbook(await obj.text())
    except ValueError as e:
        raise HTTPException(422, f"this version no longer validates: {str(e)[:300]}") from None
    was = await db.prepare("SELECT name, version, sha256 FROM playbooks WHERE active = 1").first()
    await db.batch(
        [
            db.prepare("UPDATE playbooks SET active = 0"),
            db.prepare("UPDATE playbooks SET active = 1 WHERE name = ? AND version = ?").bind(body.name, body.version),
        ]
    )
    await log_switch(env, was, body.name, body.version, row["sha256"], who["actor"])
    return {"name": body.name, "version": body.version, "sha256": row["sha256"], "active": True}


def gateway(env):
    """Every Workers AI call goes through AI Gateway, for logs, caching and rate limits."""
    return {"gateway": {"id": env.AI_GATEWAY_ID}}


async def ai_run(env, model, inputs):
    """env.AI.run through AI Gateway, timed. The newest call is kept for the Under the hood panel."""
    t0 = time.time()
    ok = False
    try:
        res = await env.AI.run(model, inputs, gateway(env))
        ok = True
        return res
    finally:
        last = {"model": model, "ms": round((time.time() - t0) * 1000), "ok": ok, "at": int(time.time() * 1000),
                "gateway": env.AI_GATEWAY_ID, "log_id": getattr(env.AI, "aiGatewayLogId", None)}  # fmt: skip
        try:
            await env.DB.prepare(SET_SETTING).bind("ai_last", json.dumps(last)).run()
        except Exception as e:  # noqa: BLE001 - the panel is best effort, never the AI answer
            print(f"ai_last update failed: {e}")


SET_SETTING = "INSERT INTO settings (k, v) VALUES (?, ?) ON CONFLICT (k) DO UPDATE SET v = excluded.v"
ADD_SETTING = (
    "INSERT INTO settings (k, v) VALUES (?, ?) "
    "ON CONFLICT (k) DO UPDATE SET v = CAST(v AS INTEGER) + CAST(excluded.v AS INTEGER)"
)


async def embed(env, pb, texts):
    return (await ai_run(env, pb.ai.embedding_model, {"text": texts}))["data"]


async def index_knowledge(env, pb):
    """Embed the playbook's guidance and store it in Vectorize. The playbook is active either way."""
    if not pb.ai or not pb.knowledge:
        return {"indexed": 0}
    try:
        vectors = await embed(env, pb, [f"{d.title}. {d.text}" for d in pb.knowledge])
        # The id is all Vectorize needs to hold: titles and text are read from the active playbook.
        await env.VECTORIZE.upsert([{"id": f"{pb.name}:{d.id}", "values": list(v)} for d, v in zip(pb.knowledge, vectors)])
        return {"indexed": len(vectors)}
    except Exception as e:  # noqa: BLE001 - any Workers AI or Vectorize failure is reported, not raised
        print(f"knowledge indexing failed: {e}")
        return {"indexed": 0, "error": str(e)[:300]}


async def retrieve(env, pb, query):
    """The playbook guidance closest to `query`. Empty if retrieval fails: the assistant then answers without it."""
    try:
        res = await env.VECTORIZE.query(list((await embed(env, pb, [query]))[0]), {"topK": pb.ai.top_k + 5})
        docs = {f"{pb.name}:{d.id}": d for d in pb.knowledge}
        # Vectors from older playbook versions can linger in the index. Only current documents count.
        print("guidance scores:", [(m["id"], round(m["score"], 2)) for m in res["matches"][:4]])
        # A weak match is noise, not guidance: it must clear the floor and sit close to the best match.
        floor = max(pb.ai.min_score, max((m["score"] for m in res["matches"]), default=0) - pb.ai.score_margin)
        close = [m for m in res["matches"] if m["score"] >= floor]
        return [docs[m["id"]] for m in close if m["id"] in docs][: pb.ai.top_k]
    except Exception as e:  # noqa: BLE001
        print(f"guidance retrieval failed: {e}")
        return []


class Ask(BaseModel):
    alert_id: str | None = Field(default=None, max_length=200)
    question: str | None = Field(default=None, max_length=500)


_last_ask = {}


@app.post("/api/astronauts/{entity_id}/explain")
async def explain(entity_id: str, body: Ask, request: Request):
    """The assistant explains an active alert or answers a question. It explains, guides and escalates. It never diagnoses."""
    env = request.scope["env"]
    who = need_crew(request, entity_id)
    await require_crew(env, entity_id)
    pb = await active_playbook(env)
    if not pb or not pb.ai:
        raise HTTPException(409, "the active playbook has no ai section")
    question = (body.question or "").strip() or None
    # shortcut: one request per user every 3 s per isolate, move to a Rate Limiting binding if abused
    if time.time() - _last_ask.get(who["actor"], 0) < 3:
        raise HTTPException(429, "wait a few seconds before asking again")
    _last_ask[who["actor"]] = time.time()

    st = await env.ASTRONAUT.getByName(entity_id).status()
    alert = next((a for a in (st or {}).get("alerts", []) if a["id"] == body.alert_id), None)
    if body.alert_id and not alert:
        raise HTTPException(404, "that alert is no longer active")
    if not alert and not question:
        raise HTTPException(422, "send an alert_id, a question, or both")

    topic = None
    if alert:
        # Naming the indicator and its domain makes a short alert message match its guidance.
        domain = pb.domains[alert["domain"]]
        topic = f'{domain.indicators[alert["metric"]].label}. {domain.label}. {alert["message"]}'
    docs = await retrieve(env, pb, " ".join(x for x in (topic, question) if x))
    messages = [
        {"role": "system", "content": pb.ai.prompt},
        {"role": "user", "content": engine.explain_prompt(pb, st, alert, question, docs)},
    ]
    try:
        res = await ai_run(env, pb.ai.model, {"messages": messages, "max_tokens": pb.ai.max_tokens, "temperature": 0.2})
        answer = (res["response"] or "").strip()
    except Exception as e:  # noqa: BLE001
        print(f"assistant failed: {e}")
        raise HTTPException(502, "the assistant did not answer") from None
    if not answer:
        raise HTTPException(502, "the assistant returned an empty answer")
    sources = [d.title for d in docs]
    payload = {"alert_id": body.alert_id, "question": question, "answer": answer, "sources": sources, "model": pb.ai.model}
    # Free questions are private, like a conversation. So is anything about an alert the crew member has not shared.
    choices = await env.ASTRONAUT.getByName(entity_id).choices()
    if alert and engine.alert_open(pb, alert["domain"], alert["metric"]):
        summary = f'{pb.ai.role} answered about "{alert["message"]}"'
    else:
        summary, payload = f"{pb.ai.role} answered a private question. Only the crew member can see it.", ledger.sealed(payload)
    await ledger_log(env, "recommendation", summary, payload, entity_id)
    return {"role": pb.ai.role, "answer": answer, "sources": sources}


@app.get("/api/playbook")
async def get_playbook(request: Request):
    pb = await active_playbook(request.scope["env"])
    if not pb:
        raise HTTPException(404, "no active playbook")
    return pb.model_dump()


_delay_cache = {"at": 0.0, "s": None, "demo": False}


async def delay_settings(env):
    """The fallback fixed delay from PUT /api/mission (`s`), and whether a demo replay is loaded (`demo`). Cached 5 s per isolate."""
    c = _delay_cache
    if time.time() - c["at"] > 5:
        res = await env.DB.prepare("SELECT k, v FROM settings WHERE k IN ('comm_delay_s', 'demo_scenario')").all()
        found = {r["k"]: r["v"] for r in res["results"]}
        c.update(at=time.time(), s=int(found["comm_delay_s"]) if "comm_delay_s" in found else None, demo="demo_scenario" in found)
    return c


async def fixed_delay(env, demo=None):
    """Earth's fixed delay in seconds, or None for the real light delay. `demo`: answer for a replay, loaded or not.

    The active playbook's mission.comm_delay decides. A demo replay shortens the real light delay to DEMO_DELAY_S,
    so a visitor sees Earth catch up without waiting 3 to 22 minutes. The PUT /api/mission setting is only the
    fallback when no active playbook has a mission block.
    """
    c = await delay_settings(env)
    pb = await active_playbook(env)
    if pb and pb.mission:
        if pb.mission.comm_delay != "real_light_delay":
            return pb.mission.comm_delay.fixed_seconds
        return DEMO_DELAY_S if (c["demo"] if demo is None else demo) else None
    return c["s"]


async def comm_delay(env, ts):
    """Seconds a message takes to reach Earth at mission time `ts`: fixed, or the real Earth-Mars light time."""
    fixed = await fixed_delay(env)
    return round(space.sky(ts)["light_s"]) if fixed is None else fixed


class MissionSettings(BaseModel):
    comm_delay_s: int | None = Field(ge=0, le=1500)  # null restores the real light delay (3 to 22 minutes)


@app.get("/api/mission")
async def get_mission(request: Request):
    """comm_delay_s: the delay in force (null means the real light delay). PUT only sets the fallback."""
    return {"comm_delay_s": await fixed_delay(request.scope["env"])}


@app.put("/api/mission")
async def put_mission(body: MissionSettings, request: Request):
    env = request.scope["env"]
    need_role(request, "commander")
    no_guest(request)
    if body.comm_delay_s is None:
        await env.DB.prepare("DELETE FROM settings WHERE k = 'comm_delay_s'").run()
    else:
        await (
            env.DB.prepare("INSERT INTO settings (k, v) VALUES ('comm_delay_s', ?) ON CONFLICT (k) DO UPDATE SET v = excluded.v")
            .bind(str(body.comm_delay_s))
            .run()
        )
    _delay_cache["at"] = 0
    return body


@app.get("/api/earth/astronauts/{entity_id}")
async def earth_view(entity_id: str, request: Request):
    """What Earth has received so far for this crew member: readings and status as of one comm delay ago."""
    env = request.scope["env"]
    who = need_earth(request, entity_id)
    view = await env.ASTRONAUT.getByName(entity_id).earth_view(who["role"] == "flight_surgeon" or auth.acts_as(who, entity_id))
    return {"comm_delay_s": await fixed_delay(env), **view}


# ---- Space weather: NASA DONKI ----

DONKI_CREDIT = "NASA CCMC DONKI"
MAX_RANGE_DAYS = 200


def donki_url(env, kind, month):
    year, mon = (int(x) for x in month.split("-"))
    query = f"{kind}?startDate={month}-01&endDate={month}-{calendar.monthrange(year, mon)[1]:02d}"
    key = getattr(env, "NASA_API_KEY", None)
    # With a key: api.nasa.gov. Without: the CCMC host DONKI itself runs on, which needs no key.
    return f"https://api.nasa.gov/DONKI/{query}&api_key={key}" if key else f"https://kauai.ccmc.gsfc.nasa.gov/DONKI/WS/get/{query}"


# ---- Tiger Data (TimescaleDB) via the vop-tiger Worker: long-term history ----


def js(obj):
    return to_js(obj, dict_converter=Object.fromEntries)


async def tiger_insert(env, by_entity):
    """Copy readings into the hypertable in one batched insert. Best effort: the live path never waits on history."""
    rows = [{**{k: r.get(k) for k in ("domain", "metric", "value", "unit", "source", "ts")}, "entity_id": e}
            for e, readings in by_entity.items() for r in readings]  # fmt: skip
    if not rows:
        return
    try:
        await env.TIGER.insertIndicators(js(rows))
    except Exception as e:  # noqa: BLE001
        # shortcut: a Tiger outage loses these rows from history, add a retry queue if that matters
        print(f"tiger insert failed: {e}")


async def tiger_history(env, entity_id, days):
    return _py(await env.TIGER.history(entity_id, days))


async def load_month(env, kind, month, refresh=False):
    """Make sure one kind of DONKI event for one month is in D1. Raw JSON goes to R2. False if DONKI did not answer."""
    db = env.DB
    done = await db.prepare("SELECT 1 FROM sw_months WHERE kind = ? AND month = ?").bind(kind, month).first()
    if done and not refresh:
        return True
    try:
        res = await fetch(donki_url(env, kind, month))
        if res.status in (401, 403) and getattr(env, "NASA_API_KEY", None):
            # A revoked or mistyped key: NASA's public DEMO_KEY still answers, and each month is fetched once.
            res = await fetch(donki_url(env, kind, month).rsplit("api_key=", 1)[0] + "api_key=DEMO_KEY")
        if res.status != 200:
            raise OSError(f"HTTP {res.status}")
        text = await res.text()
        raw = json.loads(text) if text.strip() else []  # DONKI sends an empty body when a month has no events
    except (OSError, ValueError) as e:
        print(f"DONKI {kind} {month} failed: {e}")
        return bool(done)  # a failed refresh keeps what is already stored
    await env.BUCKET.put(f"donki/{kind}/{month}.json", text)
    rows = space.normalize(kind, raw)
    stmts = [
        db.prepare("INSERT OR REPLACE INTO sw_events (id, type, time, data) VALUES (?, ?, ?, ?)").bind(r["id"], kind, r["time"], json.dumps(r))
        for r in rows
    ]
    stmts.append(db.prepare("INSERT OR REPLACE INTO sw_months (kind, month, fetched_at) VALUES (?, ?, ?)").bind(kind, month, int(time.time() * 1000)))
    for i in range(0, len(stmts), 50):
        await db.batch(stmts[i : i + 50])
    try:
        await env.TIGER.insertDonki(js([{"id": r["id"], "type": kind, "time": r["time"], "data": r} for r in rows if r.get("time")]))
    except Exception as e:  # noqa: BLE001 - D1 has the events; Tiger is the long-term copy
        print(f"tiger DONKI insert failed: {e}")
    return True


def months_between(start: date, end: date):
    out, d = [], start.replace(day=1)
    while d <= end:
        out.append(f"{d.year}-{d.month:02d}")
        d = (d + timedelta(days=32)).replace(day=1)
    return out


def day_ms(d: date):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


async def events_between(env, start: date, end: date):
    """DONKI events in [start, end], fetching any month not stored yet. Returns (events, kinds DONKI did not answer for)."""
    if end < start or (end - start).days > MAX_RANGE_DAYS:
        raise HTTPException(422, f"end must be on or after start, at most {MAX_RANGE_DAYS} days later")
    jobs = [(kind, month) for month in months_between(start, end) for kind in space.KINDS]
    ok = await asyncio.gather(*(load_month(env, kind, month) for kind, month in jobs))
    missing = sorted({kind for (kind, _), good in zip(jobs, ok) if not good})
    res = await (
        env.DB.prepare("SELECT data FROM sw_events WHERE time >= ? AND time < ? ORDER BY time")
        .bind(day_ms(start), day_ms(end) + 86_400_000)
        .all()
    )
    return [json.loads(r["data"]) for r in res["results"]], missing


_dose_cache = {}


async def dose_points(env, pb, start: date, end: date, step_min, shielding):
    """Modeled dose from `start` to the end of `end`. Cached per isolate: scrubbing asks for the same series again and again."""
    key = (pb.name, pb.version, start, end, step_min, shielding)
    if key not in _dose_cache:
        # Events from the days before the window still matter: their tails reach into it.
        events, missing = await events_between(env, start - timedelta(days=5), end)
        points = space.dose_series(events, day_ms(start), day_ms(end) + 86_400_000, step_min * 60_000, pb.space_weather.model, shielding)
        if len(_dose_cache) >= 8:
            _dose_cache.clear()
        _dose_cache[key] = (points, missing)
    return _dose_cache[key]


async def space_playbook(env):
    pb = await active_playbook(env)
    if not pb or not pb.space_weather:
        raise HTTPException(409, "the active playbook has no space_weather section")
    return pb


@app.get("/api/space-weather")
async def space_weather(request: Request, start: date, end: date):
    events, missing = await events_between(request.scope["env"], start, end)
    return {"start": start, "end": end, "events": events, "missing": missing, "credit": DONKI_CREDIT}


@app.get("/api/space-weather/dose")
async def space_weather_dose(
    request: Request,
    start: date,
    end: date,
    step_min: int = Query(60, ge=10, le=1440),
    shielding: float = Query(1, gt=0, le=1),
):
    """Crew dose modeled from DONKI events: [[ts, mSv/day, cumulative mSv since start], ...]."""
    env = request.scope["env"]
    points, missing = await dose_points(env, await space_playbook(env), start, end, step_min, shielding)
    return {"points": points, "missing": missing, "credit": DONKI_CREDIT, "note": "modeled from DONKI events, not measured"}


@app.get("/api/space-weather/twin")
async def space_weather_twin(request: Request, start: date, end: date, at: datetime):
    """Storm replay: what the playbook engine and its twin conclude at time `at`, fed the modeled dose since `start`.

    `end` is the end of the replay window. The dose series is built once for the whole window and cached,
    so scrubbing only repeats the cheap part, the engine run up to `at`.
    """
    env = request.scope["env"]
    pb = await space_playbook(env)
    at_ms = int((at if at.tzinfo else at.replace(tzinfo=timezone.utc)).timestamp() * 1000)
    if not day_ms(start) <= at_ms <= day_ms(end) + 86_400_000:
        raise HTTPException(422, "at must be between start and end")
    points, missing = await dose_points(env, pb, start, end, 30, 1.0)
    events, _ = await events_between(env, start, end)  # stored by dose_points above, so no DONKI call
    triggers = [t for t in space.triggers(events) if t["ts"] >= day_ms(start)]
    sw, state, now = pb.space_weather, engine.new_state(), points[0]
    for point in points:
        if point[0] > at_ms:
            break
        while triggers and triggers[0]["ts"] <= point[0]:  # DONKI rules fire at the event, in time order
            engine.donki_step(pb, state, triggers.pop(0))
        now = point
        engine.step(pb, state, {"domain": sw.dose_rate.domain, "metric": sw.dose_rate.metric, "value": point[1], "ts": point[0]})
        engine.step(pb, state, {"domain": sw.cumulative_dose.domain, "metric": sw.cumulative_dose.metric, "value": point[2], "ts": point[0]})
    return {"at": now[0], "dose_rate": now[1], "cumulative_dose": now[2], "status": engine.status(pb, state), "missing": missing}


@app.get("/api/astronauts/{entity_id}/status")
async def astronaut_status(entity_id: str, request: Request):
    need_crew(request, entity_id)
    return await request.scope["env"].ASTRONAUT.getByName(entity_id).status()


@app.get("/api/hood")
async def under_the_hood(request: Request):
    """Live Cloudflare internals for mission control: Durable Objects, queue backlog, AI Gateway, ledger, Workflows."""
    env = request.scope["env"]
    need_role(request, *auth.MISSION)
    db = env.DB
    crew_ids = [r["entity_id"] for r in (await db.prepare("SELECT entity_id FROM crew ORDER BY entity_id").all())["results"]]
    objects, head, settings, open_incidents = await asyncio.gather(
        asyncio.gather(*(env.ASTRONAUT.getByName(i).hood() for i in crew_ids)),
        ledger_stub(env).head(),
        db.prepare("SELECT k, v FROM settings WHERE k IN ('q_sent', 'q_done', 'ai_last')").all(),
        db.prepare("SELECT id, entity_id, message, stage, created_ts FROM incidents WHERE stage IN ('starting', 'notified') "
                   "ORDER BY created_ts DESC LIMIT 10").all(),  # fmt: skip
    )
    kv = {r["k"]: r["v"] for r in settings["results"]}
    incidents = open_incidents["results"]
    statuses = await asyncio.gather(*(workflow_status(env, i["id"]) for i in incidents))
    return {
        "durable_objects": [{"name": f"Astronaut {i}", **_py(o)} for i, o in zip(crew_ids, objects)] + [{"name": "Ledger main"}],
        "queue": {"name": "vop-indicators", "sent": int(kv.get("q_sent", 0)), "done": int(kv.get("q_done", 0)),
                  "backlog": max(0, int(kv.get("q_sent", 0)) - int(kv.get("q_done", 0)))},  # fmt: skip
        "ai_last": json.loads(kv["ai_last"]) if "ai_last" in kv else None,
        "ledger_head": head,
        "workflows": [{**dict(i), "status": st} for i, st in zip(incidents, statuses)],
        "now": int(time.time() * 1000),
    }


@app.get("/api/astronauts/{entity_id}/history")
async def astronaut_history(entity_id: str, request: Request, days: int = 30):
    """Daily averages per indicator from Tiger Data (time_bucket), ending at this crew member's newest reading."""
    env = request.scope["env"]
    need_crew(request, entity_id)
    if days not in (30, 90, 180):  # a Literal of ints does not accept the query string "30"
        raise HTTPException(422, "days must be 30, 90 or 180")
    try:
        daily = await tiger_history(env, entity_id, days)
    except Exception as e:  # noqa: BLE001
        print(f"tiger history failed: {e}")
        raise HTTPException(502, "history is not available right now") from None
    series = {}
    for row in daily:
        series.setdefault((row["domain"], row["metric"]), []).append([row["day"], row["avg"]])
    pb = await active_playbook(env)
    return {
        "days": days,
        "series": [{"domain": d, "metric": m, "points": pts} for (d, m), pts in series.items()],
        "chronic": engine.chronic_trends(pb, daily) if pb else {},
    }


@app.get("/api/astronauts/{entity_id}/earth-link")
async def astronaut_earth_link(entity_id: str, request: Request):
    """The Durable Object alarm that delivers to Earth: when it next fires, and what Earth has so far."""
    need_crew(request, entity_id)
    return await request.scope["env"].ASTRONAUT.getByName(entity_id).earth_link()


MAX_READINGS = 5000  # per request
CHUNK = 300  # readings per queue message, keeps each well under the 128 KB limit


@app.post("/api/ingest", status_code=202)
async def ingest(readings: list[Indicator], request: Request, x_ingest_key: str = Header("")):
    env = request.scope["env"]
    require_key(env, x_ingest_key)
    if len(readings) > MAX_READINGS:
        raise HTTPException(413, f"at most {MAX_READINGS} readings per request")

    by_entity = {}
    for r in readings:
        row = r.model_dump(exclude={"entity_id", "timestamp"}, exclude_none=True)
        row["ts"] = int(r.timestamp.timestamp() * 1000)
        by_entity.setdefault(r.entity_id, []).append(row)
    sent = 0
    for entity_id, rows in by_entity.items():
        for i in range(0, len(rows), CHUNK):
            await env.INDICATORS.send({"entity_id": entity_id, "readings": rows[i : i + CHUNK]})
            sent += 1
    await count_queue(env, "q_sent", sent)
    return {"queued": len(readings)}


async def count_queue(env, k, n):
    """Queue backlog for the Under the hood panel: q_sent minus q_done. Best effort, never blocks ingest."""
    if n:
        try:
            await env.DB.prepare(ADD_SETTING).bind(k, str(n)).run()
        except Exception as e:  # noqa: BLE001
            print(f"{k} count failed: {e}")


@app.get("/api/crew")
async def crew(request: Request):
    """Mission control sees the whole crew. A crew member sees only themself."""
    who = request.state.who
    res = await request.scope["env"].DB.prepare("SELECT * FROM crew ORDER BY entity_id").all()
    return [r for r in res["results"] if who["role"] in auth.MISSION or auth.acts_as(who, r["entity_id"])]


@app.get("/api/habitat")
async def habitat(request: Request):
    """Modules with their crew and the group-wide warnings spreading through them. Mission control only."""
    env = request.scope["env"]
    need_role(request, *auth.MISSION)
    res = await env.DB.prepare("SELECT entity_id, module FROM crew ORDER BY entity_id").all()
    crew = []
    for r in res["results"]:
        h = _py(await env.ASTRONAUT.getByName(r["entity_id"]).habitat())
        crew.append({"entity_id": r["entity_id"], **h, "module": h["module"] or r["module"]})
    return crew


@app.get("/api/astronauts/{entity_id}/latest")
async def latest(entity_id: str, request: Request):
    need_crew(request, entity_id)
    res = await (
        request.scope["env"]
        .DB.prepare("SELECT * FROM latest WHERE entity_id = ? ORDER BY domain, metric")
        .bind(entity_id)
        .all()
    )
    return res["results"]


async def require_crew(env, entity_id):
    """Crew members are created by keyed sensor ingest only, so writes for unknown ids are refused."""
    if not await env.DB.prepare("SELECT 1 FROM crew WHERE entity_id = ?").bind(entity_id).first():
        raise HTTPException(404, "unknown crew member")


class StepDone(BaseModel):
    alert_id: str = Field(max_length=200)
    step: int = Field(ge=0)


@app.get("/api/astronauts/{entity_id}/checklists")
async def checklist_progress(entity_id: str, request: Request):
    need_crew(request, entity_id)
    res = await (
        request.scope["env"]
        .DB.prepare("SELECT alert_id, step FROM checklist_steps WHERE entity_id = ? ORDER BY done_ts DESC LIMIT 500")
        .bind(entity_id)
        .all()
    )
    return res["results"]


@app.post("/api/astronauts/{entity_id}/checklists", status_code=201)
async def checklist_step_done(entity_id: str, body: StepDone, request: Request):
    env = request.scope["env"]
    who = need_crew(request, entity_id)
    db = env.DB
    alert = await db.prepare("SELECT detail FROM alerts WHERE id = ? AND entity_id = ?").bind(body.alert_id, entity_id).first()
    if not alert:
        raise HTTPException(404, "unknown alert")
    pb = await active_playbook(env)
    checklist = pb and pb.checklists.get(json.loads(alert["detail"]).get("checklist"))
    if not checklist or body.step >= len(checklist.steps):
        raise HTTPException(422, "this alert has no such checklist step")
    res = await (
        db.prepare("INSERT OR IGNORE INTO checklist_steps (alert_id, step, entity_id, done_ts) VALUES (?, ?, ?, ?)")
        .bind(body.alert_id, body.step, entity_id, int(time.time() * 1000))
        .run()
    )
    if res["meta"]["changes"]:  # a step marked done twice is logged once
        detail = json.loads(alert["detail"])
        summary, payload = f'Step {body.step + 1} of "{checklist.title}" done: {checklist.steps[body.step]}', {"alert_id": body.alert_id, "step": body.step}
        if not engine.alert_open(pb, detail["domain"], detail["metric"]):
            summary, payload = f"Step {body.step + 1} of a private checklist done.", ledger.sealed(payload)
        await ledger_log(
            env, "checklist_step", summary, payload, entity_id,
            actor=who["actor"],
            key=f"step:{body.alert_id}:{body.step}",
        )  # fmt: skip
        done = await db.prepare("SELECT count(*) AS n FROM checklist_steps WHERE alert_id = ?").bind(body.alert_id).first()
        if done["n"] >= len(checklist.steps):
            await incident_event(env, body.alert_id, {"by": who["actor"], "steps": done["n"]})
    return {"alert_id": body.alert_id, "step": body.step}


# ---- Incident response: a Cloudflare Workflow per critical alert that comes with a checklist ----

SHELTER_TIMEOUT = "10 minutes"  # shortcut: one mission-wide value, move it into the playbook if missions differ


def incident_id(alert_id):
    """Workflow instance ids allow letters, digits, - and _ only. One instance per alert: a queue retry reuses it."""
    return "incident-" + hashlib.sha256(alert_id.encode()).hexdigest()[:32]


async def incident_stage(env, iid, stage):
    await env.DB.prepare("UPDATE incidents SET stage = ?, updated_ts = ? WHERE id = ?").bind(stage, int(time.time() * 1000), iid).run()


async def start_incident(env, entity_id, alert_id, a):
    iid = incident_id(alert_id)
    now = int(time.time() * 1000)
    await (
        env.DB.prepare(
            "INSERT OR IGNORE INTO incidents (id, entity_id, alert_id, message, stage, created_ts, updated_ts) "
            "VALUES (?, ?, ?, ?, 'starting', ?, ?)"
        )
        .bind(iid, entity_id, alert_id, a["message"], now, now)
        .run()
    )
    params = {"entity_id": entity_id, "alert_id": alert_id, "message": a["message"], "checklist": a["checklist"]}
    try:
        await env.INCIDENT.create(to_js({"id": iid, "params": params}, dict_converter=Object.fromEntries))
    except Exception as e:
        if "already" not in str(e).lower():  # a queue retry of the same readings: the instance is running
            raise


async def incident_event(env, alert_id, payload):
    """The shelter checklist is complete: wake the alert's Workflow, if it has one and is still waiting."""
    if not await env.DB.prepare("SELECT 1 FROM incidents WHERE alert_id = ?").bind(alert_id).first():
        return
    try:
        inst = await env.INCIDENT.get(incident_id(alert_id))
        await inst.sendEvent(to_js({"type": "shelter_done", "payload": payload}, dict_converter=Object.fromEntries))
    except Exception as e:  # noqa: BLE001 - the step is logged either way; the Workflow's timeout still pages
        print(f"incident event failed: {e}")


def _py(x):
    return x.to_py() if hasattr(x, "to_py") else x


class IncidentResponse(WorkflowEntrypoint):
    """notify crew -> wait for the shelter checklist -> page the commander if it times out. Every step is logged."""

    async def run(self, event, step):
        ev = _py(event)
        p = _py(ev["payload"] if isinstance(ev, dict) else ev.payload)
        env, iid, eid = self.env, incident_id(p["alert_id"]), p["entity_id"]

        async def log(name, summary, payload):
            await ledger_log(env, "workflow_step", summary, {"workflow": iid, "step": name, **payload}, eid,
                             actor="incident-workflow", key=f"wf:{iid}:{name}")  # fmt: skip
            await incident_stage(env, iid, name)

        @step.do("notify crew")
        async def notify():
            msg = json.dumps({"type": "incident", "stage": "notified", "message": p["message"], "checklist": p["checklist"]})
            await env.ASTRONAUT.getByName(eid).incident(msg)
            await log("notified", f'Incident response: crew told to shelter for "{p["message"]}". Waiting up to {SHELTER_TIMEOUT}.', {})
            return True

        await notify()
        try:
            done = _py(await step.wait_for_event("wait for shelter checklist", "shelter_done", timeout=SHELTER_TIMEOUT))
        except Exception as e:  # noqa: BLE001 - WorkflowTimeoutError: nobody finished the checklist in time
            if "time" not in str(e).lower():
                raise

            @step.do("page commander")
            async def page():
                await log("paged", f"Incident response: shelter checklist not finished within {SHELTER_TIMEOUT}. Commander paged.",
                          {"role": "commander"})  # fmt: skip
                return "paged"

            return await page()

        got = _py(done.get("payload")) if isinstance(done, dict) else None

        @step.do("checklist complete")
        async def complete():
            await log("sheltered", "Incident response: shelter checklist completed. No page needed.", {"event": got})
            return "sheltered"

        return await complete()


@app.get("/api/astronauts/{entity_id}/incident")
async def astronaut_incident(entity_id: str, request: Request):
    """The newest incident-response Workflow for this crew member and its live status from Workflows. Null if none."""
    env = request.scope["env"]
    need_crew(request, entity_id)
    row = await env.DB.prepare("SELECT * FROM incidents WHERE entity_id = ? ORDER BY created_ts DESC LIMIT 1").bind(entity_id).first()
    if not row:
        return None
    return {**dict(row), "status": await workflow_status(env, row["id"]), "timeout": SHELTER_TIMEOUT}


async def workflow_status(env, iid):
    try:
        st = _py(await (await env.INCIDENT.get(iid)).status())
        return st.get("status") if isinstance(st, dict) else str(st)
    except Exception as e:  # noqa: BLE001
        print(f"incident status failed: {e}")
        return "unknown"


class CheckinAnswers(BaseModel):
    answers: dict[str, float | str]


@app.get("/api/astronauts/{entity_id}/checkin")
async def last_checkin(entity_id: str, request: Request):
    """When the last check-in happened. Answers are not returned: they are private."""
    need_crew(request, entity_id)
    db = request.scope["env"].DB
    row = await db.prepare("SELECT max(ts) AS ts, max(created_at) AS at FROM checkins WHERE entity_id = ?").bind(entity_id).first()
    # The daily cron's reminder stays due until a check-in is saved after it was sent.
    sent = await db.prepare("SELECT CAST(v AS INTEGER) AS at FROM settings WHERE k = ?").bind(f"reminder:{entity_id}").first()
    return {"ts": row["ts"], "due": bool(sent and sent["at"] > (row["at"] or 0))}


@app.get("/api/astronauts/{entity_id}/report")
async def latest_report(entity_id: str, request: Request):
    """The newest weekly report, markdown. It covers private indicators, so only that crew member can read it."""
    need_crew(request, entity_id)
    env = request.scope["env"]
    listing = await env.BUCKET.list(to_js({"prefix": f"reports/{entity_id}/"}, dict_converter=Object.fromEntries))
    keys = sorted(o.key for o in listing.objects)
    obj = await env.BUCKET.get(keys[-1]) if keys else None
    if not obj:
        raise HTTPException(404, "no weekly report yet")
    return PlainTextResponse(await obj.text(), media_type="text/markdown")


@app.post("/api/astronauts/{entity_id}/checkin", status_code=201)
async def submit_checkin(entity_id: str, body: CheckinAnswers, request: Request):
    env = request.scope["env"]
    need_crew(request, entity_id)
    await require_crew(env, entity_id)
    pb = await active_playbook(env)
    if not pb or not pb.checkin:
        raise HTTPException(409, "the active playbook has no check-in")
    try:
        readings, answers = engine.checkin_readings(pb, body.answers)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    # Straight to the Durable Object, not the queue: the crew member gets rules and guidance at once.
    ts = await env.ASTRONAUT.getByName(entity_id).checkin(entity_id, readings)
    await (
        env.DB.prepare("INSERT INTO checkins (entity_id, ts, created_at, answers) VALUES (?, ?, ?, ?)")
        .bind(entity_id, ts, int(time.time() * 1000), json.dumps(answers))
        .run()
    )
    return {"ts": ts}


# ---- Sharing with Earth ----


class Share(BaseModel):
    domain: str = Field(max_length=100)
    metric: str = Field(max_length=100)
    shared: bool


@app.get("/api/astronauts/{entity_id}/sharing")
async def get_sharing(entity_id: str, request: Request):
    need_crew(request, entity_id)
    return await request.scope["env"].ASTRONAUT.getByName(entity_id).sharing()


@app.put("/api/astronauts/{entity_id}/sharing")
async def put_sharing(entity_id: str, body: Share, request: Request):
    """Start or stop sharing one indicator with Earth. Every change is logged before it takes effect."""
    env = request.scope["env"]
    who = need_crew(request, entity_id)
    await require_crew(env, entity_id)
    pb = await active_playbook(env)
    spec = pb and pb.domains.get(body.domain) and pb.domains[body.domain].indicators.get(body.metric)
    if not spec:
        raise HTTPException(404, "the active playbook has no such indicator")
    if spec.privacy == "always_shared":
        raise HTTPException(422, f"{spec.label} is always shared: the playbook marks it safety-critical")
    astronaut = env.ASTRONAUT.getByName(entity_id)
    if engine.is_shared(pb, await astronaut.choices(), body.domain, body.metric) != body.shared:
        # Logged first: if the change then fails and is retried, the log has a duplicate, never a gap.
        verb = "started sharing" if body.shared else "stopped sharing"
        whom = "the flight surgeon" if spec.privacy == "private" else "mission control"
        await ledger_log(
            env, "data_share", f"{entity_id} {verb} {spec.label} with {whom}.",
            {"domain": body.domain, "metric": body.metric, "shared": body.shared}, entity_id, actor=who["actor"],
        )  # fmt: skip
        await astronaut.set_share(entity_id, body.domain, body.metric, body.shared)
    return {"domain": body.domain, "metric": body.metric, "shared": body.shared}


class CheckinShare(BaseModel):
    shared: bool


@app.put("/api/astronauts/{entity_id}/checkin/sharing")
async def put_checkin_sharing(entity_id: str, body: CheckinShare, request: Request):
    """Share or unshare every indicator the daily check-in feeds, as one logged choice. Free-text answers never leave."""
    env = request.scope["env"]
    who = need_crew(request, entity_id)
    await require_crew(env, entity_id)
    pb = await active_playbook(env)
    if not pb or not pb.checkin:
        raise HTTPException(409, "the active playbook has no check-in")
    targets = sorted({(f.domain, f.metric) for f in pb.checkin.fields if f.kind != "text" and pb.domains[f.domain].indicators[f.metric].privacy != "always_shared"})
    if not targets:
        raise HTTPException(422, "every check-in indicator is always shared")
    astronaut = env.ASTRONAUT.getByName(entity_id)
    choices = await astronaut.choices()
    changed = [t for t in targets if engine.is_shared(pb, choices, *t) != body.shared]
    if changed:
        verb = "started sharing" if body.shared else "stopped sharing"
        await ledger_log(
            env, "data_share", f"{entity_id} {verb} their daily check-in with the flight surgeon.",
            {"checkin": True, "shared": body.shared, "indicators": [f"{d}/{m}" for d, m in changed]}, entity_id, actor=who["actor"],
        )  # fmt: skip
        for d, m in changed:
            await astronaut.set_share(entity_id, d, m, body.shared)
    return {"shared": body.shared, "indicators": [f"{d}/{m}" for d, m in targets]}


# ---- Black-box decision log ----

# R2 reads per verify request. Each counts toward the Worker's 1000 subrequests, and the cron spends ~60 on DONKI first.
VERIFY_MAX = 500


def demo_mode(env):
    return str(getattr(env, "DEMO_MODE", "") or "").lower() in ("1", "true", "yes")


def ledger_stub(env):
    return env.LEDGER.getByName("main")


async def ledger_log(env, type, summary, payload, entity_id=None, actor="edge-system", key=None):
    """Append one entry through the Ledger Durable Object, the only writer. Returns {"entry", "created"}.

    `actor`: the signed-in user (auth.identity), or "edge-system" for what the Worker does on its own.
    `key` makes the append idempotent: a queue retry gets the existing entry back instead of a duplicate.
    """
    pb = await active_playbook(env)  # also refreshes the cached sha of the active playbook
    fields = {
        "type": type,
        "summary": summary,
        "payload": payload,
        "entity_id": entity_id,
        "actor": actor,
        "playbook_name": pb.name if pb else None,
        "playbook_hash": _playbook_cache["sha"],
        "key": key,
    }
    return await ledger_stub(env).append(json.dumps(fields))


def stored_key(head, seq):
    """Where verify reads `seq`: the locked copy, or the demo's tampered copy while one exists."""
    if seq in head.get("tampered", []):
        return ledger.demo_key(seq, head["chain"])
    return ledger.r2_key(seq, head["chain"])


async def r2_entry(env, key):
    """The stored entry, None if the object is missing, or "unreadable" if it is not JSON."""
    obj = await env.BUCKET.get(key)
    if not obj:
        return None
    try:
        return json.loads(await obj.text())
    except ValueError:
        return "unreadable"


async def verify_chain(env, from_seq=None):
    """Re-read stored entries in seq order and check every hash and link.

    Checks at most VERIFY_MAX entries: the newest by default, or a window starting at `from_seq` to page through
    older ones. A window that does not start at genesis is anchored on the prev_hash the Ledger holds for it.
    """
    stub = ledger_stub(env)
    head = await stub.head()
    if not head:
        return {"ok": True, "checked": 0, "first_bad_seq": None, "reason": None, "complete": True, "from_seq": 0, "to_seq": -1, "head": None}
    start = max(0, head["seq"] + 1 - VERIFY_MAX) if from_seq is None else min(from_seq, head["seq"])
    end = min(head["seq"], start + VERIFY_MAX - 1)
    anchor = ledger.GENESIS_PREV if start == 0 else await stub.prev_hash_of(start)
    entries = []
    for i in range(start, end + 1, 50):  # bounded concurrency
        entries += await asyncio.gather(*(r2_entry(env, stored_key(head, s)) for s in range(i, min(i + 50, end + 1))))
    result = ledger.verify_entries(entries, start, anchor)
    # A rewritten tail can be internally consistent. The Ledger's head hash catches it.
    if result["ok"] and end == head["seq"] and entries[-1]["hash"] != head["hash"]:
        result = {**result, "ok": False, "first_bad_seq": end, "reason": f"head mismatch at seq {end}"}
    return {**result, "complete": start == 0 and end == head["seq"], "from_seq": start, "to_seq": end, "head": head}


@app.get("/api/ledger")
async def ledger_list(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    before: int | None = Query(None, ge=0),
    entity_id: str | None = Query(None, max_length=64),
    earth: bool = False,
):
    """Newest first, from the D1 index. `entity_id` keeps that crew member's entries and the mission-wide ones.

    `earth` keeps only what has reached Earth: crew entries up to the newest seq a delivered message carried,
    plus mission-wide entries and mission control's own reviews.
    """
    env = request.scope["env"]
    who = request.state.who
    if who["role"] not in auth.MISSION:  # crew: their own entries and the mission-wide ones, nobody else's
        entity_id = entity_id or who["crew_id"] or ""
        need_crew(request, entity_id)
    where, args = ("seq < ?", [before]) if before is not None else ("1", [])
    if entity_id:
        where += " AND (entity_id = ? OR entity_id IS NULL)"
        args.append(entity_id)
    if earth:
        where += " AND (seq <= ? OR entity_id IS NULL OR type LIKE 'review_%')"
        args.append(await earth_seq(env))
    res = await env.DB.prepare(f"SELECT * FROM ledger WHERE {where} ORDER BY seq DESC LIMIT ?").bind(*args, limit).all()
    return {"entries": res["results"], "demo": demo_mode(env)}


@app.get("/api/ledger/verify")
async def ledger_verify(request: Request, from_seq: int | None = Query(None, ge=0)):
    return await verify_chain(request.scope["env"], from_seq)


async def earth_seq(env):
    """The newest ledger seq a message delivered to Earth carried, or -1 if none has arrived."""
    row = await env.DB.prepare("SELECT CAST(v AS INTEGER) AS s FROM settings WHERE k = 'earth_seq'").first()
    return row["s"] if row else -1


@app.get("/api/ledger/queue")
async def ledger_queue(request: Request, earth: bool = False):
    """Entries mission control has not reviewed yet, newest first. `earth`: only those that have reached Earth."""
    env = request.scope["env"]
    need_role(request, *auth.MISSION)
    kinds = sorted(ledger.REVIEWABLE)
    upto = [await earth_seq(env)] if earth else []
    res = await (
        env.DB.prepare(
            f"SELECT * FROM ledger l WHERE type IN ({', '.join('?' * len(kinds))}) {'AND seq <= ?' if earth else ''} "
            "AND NOT EXISTS (SELECT 1 FROM ledger r WHERE r.reviewed_seq = l.seq) ORDER BY seq DESC LIMIT 100"
        )
        .bind(*kinds, *upto)
        .all()
    )
    return res["results"]


@app.get("/api/ledger/entries/{seq}")
async def ledger_entry(seq: int, request: Request):
    env = request.scope["env"]
    head = await ledger_stub(env).head()
    entry = await r2_entry(env, stored_key(head, seq)) if head and seq <= head["seq"] else None
    if not entry:
        raise HTTPException(404, "no such entry")
    if request.state.who["role"] not in auth.MISSION and isinstance(entry, dict) and entry.get("entity_id"):
        need_crew(request, entry["entity_id"])
    return entry


class Review(BaseModel):
    decision: Literal["approve", "override"]
    note: str = Field(default="", max_length=500)


@app.post("/api/ledger/review/{seq}", status_code=201)
async def ledger_review(seq: int, body: Review, request: Request):
    """Approve or override an entry. The review is a new entry pointing at `seq`; the original is never edited."""
    env = request.scope["env"]
    who = need_role(request, *auth.MISSION)
    row = await env.DB.prepare("SELECT type, summary, entity_id FROM ledger WHERE seq = ?").bind(seq).first()
    if not row:
        raise HTTPException(404, "no such entry")
    if row["type"] not in ledger.REVIEWABLE:
        raise HTTPException(422, f"{row['type']} entries are not reviewed")
    note = body.note.strip()
    if body.decision == "override" and not note:
        raise HTTPException(422, "an override needs a note saying what mission control decided instead")
    verb = "Approved" if body.decision == "approve" else "Overridden"
    res = await ledger_log(
        env, f"review_{body.decision}", f"{verb}: {row['summary']}", {"reviewed_seq": seq, "note": note},
        entity_id=row["entity_id"], actor=who["actor"], key=f"review:{seq}",
    )  # fmt: skip
    if not res["created"]:
        raise HTTPException(409, "this entry has already been reviewed")
    return res["entry"]


class Tamper(BaseModel):
    seq: int | None = Field(default=None, ge=0)


def require_demo(request):
    """Demo routes: 404 unless DEMO_MODE is on. They wipe every crew member's data, so a signed-in user must be the
    commander. A guest drives the replay in whichever role they picked: their data is only ever the replay."""
    env = request.scope["env"]
    if not demo_mode(env):
        raise HTTPException(404, "not found")
    if not request.state.who.get("guest"):
        need_role(request, "commander")
    return env


@app.post("/api/ledger/demo/tamper")
async def ledger_tamper(body: Tamper, request: Request):
    """Demo only: try to edit and delete a stored entry. R2 Bucket Lock refuses both, so the demo writes the edited
    entry to a separate demo-only copy that verify reads instead. Defaults to the newest entry."""
    env = require_demo(request)
    res = await ledger_stub(env).demo_tamper(body.seq if body.seq is not None else -1)
    if "error" in res:
        raise HTTPException(409, res["error"])
    return res


@app.post("/api/ledger/demo/restore")
async def ledger_restore(request: Request):
    """Demo only: put every tampered entry back from the Ledger's own copy."""
    env = require_demo(request)
    return await ledger_stub(env).demo_restore()


# ---- Demo mode: scripted May 2024 DONKI replay, driven by the /demo page ----


def utc_ms(*args):
    return int(datetime(*args, tzinfo=timezone.utc).timestamp() * 1000)


DEMO_WINDOW = (date(2024, 5, 1), date(2024, 5, 31))  # the dose series; inside the cron's DONKI_START..DONKI_END
DEMO_STEP_MS = 30 * 60_000  # mission time per step; the page asks for one step a second
DEMO_FOCUS = "okafor"  # the crew member whose alert the countdown follows
DEMO_DELAY_S = 20  # Earth delay during a replay, in place of the real light time
# Replays a visitor can pick, all inside DEMO_WINDOW: id -> (start, end, title, what happens).
# Each starts after a day of hourly readings, replayed at once so personal baselines are learned.
SCENARIOS = {
    "2024-05-10": (utc_ms(2024, 5, 10, 6), utc_ms(2024, 5, 12), "Solar storm begins",
                   "Quiet for 7 mission hours. At 12:59 UTC the first particle event of the May 2024 storm starts and the crew is sent to shelter."),
    "2024-05-11": (utc_ms(2024, 5, 11), utc_ms(2024, 5, 12, 12), "Storm in progress",
                   "The storm is a day old and the crew is already sheltering. Two more particle events arrive at 02:10 and 04:07 UTC."),
    "2024-05-03": (utc_ms(2024, 5, 3, 6), utc_ms(2024, 5, 4, 6), "Quiet day",
                   "No space weather. Readings stay in range, for comparison with the storm."),
}  # fmt: skip
DEMO_DEFAULT = "2024-05-10"


def demo_rows(points, t_ms, step_ms):
    """Simulated readings for every demo crew member at mission time `t_ms`, in the format Astronaut.ingest takes."""
    t = datetime.fromtimestamp(t_ms / 1000, timezone.utc)
    day_start = datetime.fromtimestamp((t_ms - step_ms) / 1000, timezone.utc).date() != t.date()
    dose = crew_sim.dose_at(points, t)
    return {
        e: [{**{k: v for k, v in r.items() if k not in ("entity_id", "timestamp")}, "ts": t_ms} for r in crew_sim.readings(e, m, t, day_start, {}, dose)]
        for e, m in crew_sim.CREW.items()
    }  # fmt: skip


async def demo_ingest(env, by_entity):
    # Straight to the Durable Objects, not the queue: each step is applied before the page asks for the next.
    await asyncio.gather(*(env.ASTRONAUT.getByName(e).ingest(e, rows) for e, rows in by_entity.items()))
    await tiger_insert(env, by_entity)


def replay_blocked(missing):
    """True when a DONKI kind the replay needs is missing for its month.

    Flares only decorate the map: rules fire on SEP and CME (DONKI_TRIGGERS). NASA's FLR endpoint can be down
    while the rest answers, and that must not block the replay.
    """
    month = f"{DEMO_WINDOW[0].year}-{DEMO_WINDOW[0].month:02d}"
    return any(m.endswith(month) and not m.startswith("FLR") for m in missing)


async def demo_missing(env):
    """DONKI (kind, month) chunks of the window not stored in D1 yet, the 5 days before it included."""
    res = await env.DB.prepare("SELECT kind, month FROM sw_months").all()
    stored = {(r["kind"], r["month"]) for r in res["results"]}
    months = months_between(DEMO_WINDOW[0] - timedelta(days=5), DEMO_WINDOW[1])
    return [f"{k} {m}" for m in months for k in space.KINDS if (k, m) not in stored]


_demo_dose = {}


async def demo_dose(env):
    """The modeled dose series, from DONKI events already in D1. Never calls NASA, so the replay has no outside calls."""
    pb = await space_playbook(env)
    key = (pb.name, pb.version)
    if key not in _demo_dose:
        start, end = DEMO_WINDOW
        if replay_blocked(await demo_missing(env)):
            raise HTTPException(409, "DONKI data for the replay month is not cached. Cache it, then start again.")
        res = await (
            env.DB.prepare("SELECT data FROM sw_events WHERE time >= ? AND time < ? ORDER BY time")
            .bind(day_ms(start - timedelta(days=5)), day_ms(end) + 86_400_000)
            .all()
        )
        events = [json.loads(r["data"]) for r in res["results"]]
        _demo_dose.clear()
        _demo_dose[key] = space.dose_series(events, day_ms(start), day_ms(end) + 86_400_000, 3_600_000, pb.space_weather.model)
    return _demo_dose[key]


async def demo_run(env):
    """(mission time of the last replayed step, or None before Start; the id of the scenario loaded)."""
    res = await env.DB.prepare("SELECT k, v FROM settings WHERE k IN ('demo_cursor', 'demo_scenario')").all()
    found = {r["k"]: r["v"] for r in res["results"]}
    scenario = found.get("demo_scenario")
    return (int(found["demo_cursor"]) if "demo_cursor" in found else None), scenario if scenario in SCENARIOS else DEMO_DEFAULT


async def demo_wipe(env):
    """Forget every crew member, alert, check-in, Earth copy and black-box entry. DONKI data, playbooks and settings stay."""
    db = env.DB
    ids = {r["entity_id"] for r in (await db.prepare("SELECT entity_id FROM crew").all())["results"]} | set(crew_sim.CREW)
    await asyncio.gather(*(env.ASTRONAUT.getByName(i).demo_reset() for i in ids))
    await ledger_stub(env).demo_reset()
    try:  # a new run learns its baselines again instead of inheriting the last run's history
        await env.TIGER.wipe(js(sorted(ids)))
    except Exception as e:  # noqa: BLE001
        print(f"tiger wipe failed: {e}")
    _delay_cache["at"] = 0
    tables = ("latest", "alerts", "checklist_steps", "checkins", "crew", "ledger", "incidents")
    await db.batch([*(db.prepare(f"DELETE FROM {t}") for t in tables), db.prepare("DELETE FROM settings WHERE k IN ('demo_cursor', 'demo_scenario', 'earth_seq')")])


async def demo_payload(env):
    cur, scenario = await demo_run(env)
    start, end = SCENARIOS[scenario][:2]
    link = await env.ASTRONAUT.getByName(DEMO_FOCUS).demo_link()
    fixed, real = await fixed_delay(env, True), round(space.sky(cur or start)["light_s"])
    return {
        "now": int(time.time() * 1000),  # the page corrects its clock with this, so the countdown matches the server
        "cursor": cur,
        "start": start,
        "end": end,
        "focus": DEMO_FOCUS,
        "crew": list(crew_sim.CREW),
        "scenario": scenario,
        "scenarios": [{"id": k, "start": v[0], "end": v[1], "title": v[2], "about": v[3]} for k, v in SCENARIOS.items()],
        "delay_s": real if fixed is None else fixed,
        "real_delay_s": real,
        "playbook_delay": await fixed_delay(env, False) is not None,  # the delay is the playbook's own, not the demo's
        **link,
    }


@app.get("/api/demo/state")
async def demo_state(request: Request):
    env = require_demo(request)
    return await demo_payload(env)


@app.post("/api/demo/prepare")
async def demo_prepare(request: Request):
    """Store the DONKI months the replay needs in D1 now, so the replay itself never calls NASA.

    `ready`: every kind is stored for the replay month. A missing earlier month only leaves its events' tails out.
    """
    env = require_demo(request)
    events, _ = await events_between(env, DEMO_WINDOW[0] - timedelta(days=5), DEMO_WINDOW[1])
    missing = await demo_missing(env)
    return {
        "events": len(events),
        "sep": sum(e["type"] == "SEP" and e["time"] >= day_ms(DEMO_WINDOW[0]) for e in events),
        "missing": missing,
        "ready": not replay_blocked(missing),
        "credit": DONKI_CREDIT,
    }


class DemoStart(BaseModel):
    scenario: str = DEMO_DEFAULT


@app.post("/api/demo/start")
async def demo_start(body: DemoStart, request: Request):
    """Wipe, replay a day of hourly readings at once so baselines are learned, and park the replay at the scenario's start."""
    env = require_demo(request)
    if body.scenario not in SCENARIOS:
        raise HTTPException(422, f"scenario must be one of {', '.join(SCENARIOS)}")
    start = SCENARIOS[body.scenario][0]
    _playbook_cache["at"] = 0  # the playbook may have just been switched in another isolate
    points = await demo_dose(env)
    await demo_wipe(env)
    # Set before the first reading, so every message of this run leaves with the demo delay.
    await env.DB.prepare("INSERT OR REPLACE INTO settings (k, v) VALUES ('demo_scenario', ?)").bind(body.scenario).run()
    _delay_cache["at"] = 0
    rows = {}
    for t in range(start - 86_400_000, start + 1, 3_600_000):
        for e, rs in demo_rows(points, t, 3_600_000).items():
            rows.setdefault(e, []).extend(rs)
    await demo_ingest(env, rows)
    # The day before the replay reached Earth long ago, so mission control starts out showing normal readings.
    await asyncio.gather(*(env.ASTRONAUT.getByName(e).demo_flush() for e in rows))
    await env.DB.prepare("INSERT OR REPLACE INTO settings (k, v) VALUES ('demo_cursor', ?)").bind(str(start)).run()
    return await demo_payload(env)


@app.post("/api/demo/step")
async def demo_step(request: Request):
    """Replay the next step of mission time for every crew member. Past the end it only reports the state."""
    env = require_demo(request)
    cur, scenario = await demo_run(env)
    if cur is None:
        raise HTTPException(409, "Start the replay first.")
    nxt = cur + DEMO_STEP_MS
    if nxt <= SCENARIOS[scenario][1]:
        points = await demo_dose(env)
        # Claimed before the ingest, so two open demo pages never replay the same mission time twice.
        claim = await env.DB.prepare("UPDATE settings SET v = ? WHERE k = 'demo_cursor' AND v = ?").bind(str(nxt), str(cur)).run()
        if claim["meta"]["changes"]:
            await demo_ingest(env, demo_rows(points, nxt, DEMO_STEP_MS))
    return await demo_payload(env)


@app.post("/api/demo/reset")
async def demo_reset(request: Request):
    env = require_demo(request)
    await demo_wipe(env)
    return await demo_payload(env)


UPSERT_D1 = (
    "INSERT INTO latest (entity_id, domain, metric, value, unit, source, ts) "
    "VALUES (?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT (entity_id, domain, metric) DO UPDATE SET value = excluded.value, "
    "unit = excluded.unit, source = excluded.source, ts = excluded.ts "
    "WHERE excluded.ts >= latest.ts"
)
UPSERT_CREW = (
    "INSERT INTO crew (entity_id, last_seen, module) VALUES (?, ?, ?) "
    "ON CONFLICT (entity_id) DO UPDATE SET last_seen = max(last_seen, excluded.last_seen), "
    "module = coalesce(excluded.module, crew.module)"
)
# DONKI events stored by load_month that trigger playbook rules in (from, to]: SEP onsets and CME arrivals at Mars.
DONKI_TRIGGERS = (
    "SELECT data FROM sw_events WHERE (type = 'SEP' AND time > ? AND time <= ?) "
    "OR (type = 'CME' AND json_extract(data, '$.mars_arrival') > ? AND json_extract(data, '$.mars_arrival') <= ?)"
)


EARTH_SEQ = (
    "INSERT INTO settings (k, v) VALUES ('earth_seq', ?) "
    "ON CONFLICT (k) DO UPDATE SET v = max(CAST(v AS INTEGER), CAST(excluded.v AS INTEGER))"
)


INSERT_ALERT = (
    "INSERT OR IGNORE INTO alerts (id, entity_id, rule_id, domain, metric, severity, message, value, baseline, "
    "detail, playbook, fired_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


class Astronaut(DurableObject):
    def _get(self, k):
        sql = self.ctx.storage.sql
        sql.exec("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
        v = sql.exec("SELECT coalesce((SELECT v FROM kv WHERE k = ?), '') AS v", k).one().v
        return json.loads(v) if v else None

    def _put(self, k, value):
        self.ctx.storage.sql.exec(
            "INSERT INTO kv VALUES (?, ?) ON CONFLICT (k) DO UPDATE SET v = excluded.v", k, json.dumps(value)
        )

    def _load_state(self):
        return self._get("state") or engine.new_state()

    async def earth_view(self, surgeon=False):
        """Earth's delayed copy. Values the crew member has since stopped sharing are hidden, not shown stale.
        Only the flight surgeon (or the crew member) gets shared private-level indicators."""
        pb = await active_playbook(self.env)
        choices = self._choices() if surgeon else engine.surgeon_only(pb, self._choices())
        earth = self._get("earth") or {"readings": {}, "status": None}
        readings, status = engine.for_earth(pb, choices, list(earth["readings"].values()), earth["status"])
        return {"readings": readings, "status": status, "withheld": engine.withheld(pb, choices)}

    def _choices(self):
        return self._get("sharing") or {}

    async def choices(self):
        """The crew member's sharing choices, "domain/metric" -> bool. Unset means the playbook default."""
        return self._choices()

    async def sharing(self):
        """Every playbook indicator, its privacy level and whether Earth receives it now."""
        pb = await active_playbook(self.env)
        choices = self._choices()
        return [
            {"domain": d, "metric": i, "privacy": spec.privacy, "shared": engine.is_shared(pb, choices, d, i)}
            for d, dom in (pb.domains.items() if pb else []) for i, spec in dom.indicators.items()
        ]  # fmt: skip

    async def set_share(self, entity_id, domain, metric, shared):
        """Record the choice, then send Earth an update: the current value when sharing starts, the status either way."""
        choices = {**self._choices(), f"{domain}/{metric}": shared}
        self._put("sharing", choices)
        pb = await active_playbook(self.env)
        state = self._load_state()
        row = await (
            self.env.DB.prepare("SELECT domain, metric, value, unit, source, ts FROM latest WHERE entity_id = ? AND domain = ? AND metric = ?")
            .bind(entity_id, domain, metric)
            .first()
        )
        readings, status = engine.for_earth(pb, choices, [dict(row)] if row else [], self._status(pb, state))
        out = json.dumps({"type": "indicators", "entity_id": entity_id, "readings": readings, "status": status,
                          "withheld": engine.withheld(pb, choices)})  # fmt: skip
        await self._send_to_earth(out, await comm_delay(self.env, state.get("clock") or int(time.time() * 1000)))

    def _outbox(self):
        sql = self.ctx.storage.sql
        sql.exec("CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, due INTEGER, body TEXT)")
        return sql

    async def _send_to_earth(self, body, delay_s, alert=False):
        """Queue a message for Earth. It leaves now and arrives one comm delay later.

        `alert`: the message carries a newly fired alert. The first one on its way is what the demo countdown shows.
        """
        due = int(time.time() * 1000) + delay_s * 1000
        self._outbox().exec("INSERT INTO outbox (due, body) VALUES (?, ?)", due, body)
        if alert and not self._get("alert_due"):
            self._put("alert_due", due)
        await self.alarm()

    async def alarm(self, *_):
        """Deliver every message whose delay has passed, then sleep until the next one is due."""
        sql = self._outbox()
        now = int(time.time() * 1000)
        due = [row.body for row in sql.exec("SELECT body FROM outbox WHERE due <= ? ORDER BY id", now)]
        if due:
            earth = self._get("earth") or {"readings": {}, "status": None}
            surgeons, limited = self.ctx.getWebSockets("surgeon"), self.ctx.getWebSockets("limited")
            pb = await active_playbook(self.env)
            hidden = engine.surgeon_only(pb, self._choices())
            seqs = []
            for body in due:
                msg = json.loads(body)
                for r in msg["readings"]:
                    earth["readings"][f'{r["domain"]}/{r["metric"]}'] = r
                    earth["upto"] = max(earth.get("upto") or 0, r["ts"])
                earth["status"] = msg["status"]
                if msg.get("ledger_seq") is not None:
                    seqs.append(msg["ledger_seq"])
                for s in surgeons:
                    s.send(body)
                if limited:
                    r, st = engine.for_earth(pb, hidden, msg["readings"], msg["status"])
                    out = json.dumps({**msg, "readings": r, "status": st, "withheld": engine.withheld(pb, hidden)})
                    for s in limited:
                        s.send(out)
            self._put("earth", earth)
            sql.exec("DELETE FROM outbox WHERE due <= ?", now)
            alert_due = self._get("alert_due")
            if alert_due and alert_due <= now:
                self._put("alert_due", None)
                self._put("alert_received", now)
            if seqs:
                try:  # a failure only delays what mission control's black box shows, never a delivery
                    await self.env.DB.prepare(EARTH_SEQ).bind(max(seqs)).run()
                except Exception as e:  # noqa: BLE001
                    print(f"earth_seq update failed: {e}")
        nxt = sql.exec("SELECT coalesce(min(due), 0) AS due FROM outbox").one().due
        if nxt:
            await self.ctx.storage.setAlarm(nxt)
        # The crew side of the link reads the real alarm, never a timer of its own.
        out = json.dumps({"type": "earth_link", **await self.earth_link()})
        for s in self.ctx.getWebSockets("crew"):
            s.send(out)

    async def hood(self):
        """For the Under the hood panel: open sockets, messages on their way to Earth, the next alarm."""
        return {
            "crew_sockets": len(self.ctx.getWebSockets("crew")),
            "earth_sockets": len(self.ctx.getWebSockets("earth")),
            "outbox": self._outbox().exec("SELECT count(*) AS n FROM outbox").one().n,
            **await self.earth_link(),
        }

    async def earth_link(self):
        """When this object's alarm next delivers to Earth, and the newest reading time Earth has received."""
        nxt = await self.ctx.storage.getAlarm()
        return {"next_alarm": int(nxt) if nxt else None, "received_upto": (self._get("earth") or {}).get("upto")}

    async def demo_flush(self):
        """Demo only: deliver everything on its way now, without changing the delay for later messages."""
        self._outbox().exec("UPDATE outbox SET due = ?", int(time.time() * 1000))
        await self.alarm()

    async def demo_link(self):
        """Demo only: the Earth link as the countdown draws it. `pending` samples the due times of messages on their way."""
        dues = [r.due for r in self._outbox().exec("SELECT due FROM outbox ORDER BY id")]
        return {
            "alert_due": self._get("alert_due"),
            "alert_received": self._get("alert_received"),
            "pending": dues[:: max(1, len(dues) // 24)],
        }

    async def demo_reset(self):
        """Demo only: forget everything, including Earth's copy and the messages still on their way."""
        _playbook_cache["at"] = _delay_cache["at"] = 0  # this isolate may still hold the last run's playbook and delay
        await self.ctx.storage.deleteAlarm()
        await self.ctx.storage.deleteAll()

    def _status(self, pb, state):
        if not pb:
            return None
        return {**engine.status(pb, state), "crew_alerts": self._get("crew_alerts") or []}

    async def status(self):
        return self._status(await active_playbook(self.env), self._load_state())

    async def crew_alert(self, msg_json):
        """Another crew member's alert that reaches this one through alert_crew (scope group or all)."""
        msg = json.loads(msg_json)
        alerts = [a for a in self._get("crew_alerts") or [] if a["key"] != msg["key"]]
        if msg["type"] == "fired":
            alerts = (alerts + [msg])[-10:]
        self._put("crew_alerts", alerts)
        status = self._status(await active_playbook(self.env), self._load_state())
        out = json.dumps({"type": "crew_alert", "entity_id": msg["to"], "status": status})
        for s in self.ctx.getWebSockets("crew"):
            s.send(out)

    async def incident(self, msg_json):
        """From the incident-response Workflow: push its step to the crew member's open screens."""
        for s in self.ctx.getWebSockets("crew"):
            s.send(msg_json)

    async def _tell_crew(self, pb, entity_id, module, e):
        """Fan an alert out to the crew it is scoped to: everyone, or the same module.

        An alert on a shared_by_group indicator (one reading stands for the whole module, e.g. cabin CO2) always
        goes to the module as a pre-warning, so mates see it before their own readings move. It is logged.
        """
        a = e["alert"]
        dom = pb and pb.domains.get(a["domain"])
        group = bool(dom and dom.shared_by_group)
        scope = a.get("alert_crew") or ("group" if group and module else None)
        if scope == "all":
            q = self.env.DB.prepare("SELECT entity_id FROM crew WHERE entity_id != ?").bind(entity_id)
        elif scope == "group" and module:
            q = self.env.DB.prepare("SELECT entity_id FROM crew WHERE entity_id != ? AND module = ?").bind(entity_id, module)
        else:
            return
        key = f'{entity_id}:{a["rule"]}'
        msg = {"key": key, "type": e["type"], "from": entity_id, "scope": scope, "prewarn": group, "module": module,
               "message": a["message"], "severity": a["severity"], "checklist": a.get("checklist"), "ts": a["ts"]}  # fmt: skip
        to = [row["entity_id"] for row in (await q.all())["results"]]
        for other in to:
            await self.env.ASTRONAUT.getByName(other).crew_alert(json.dumps({**msg, "to": other}))
        if group and to and e["type"] == "fired":
            await ledger_log(
                self.env, "pre_warn", f'Pre-warned {", ".join(to)} in {module}: {a["message"]}',
                {"from": entity_id, "to": to, "module": module, "rule": a["rule"], "severity": a["severity"]},
                entity_id, key=f'prewarn:{key}:{a["ts"]}',
            )  # fmt: skip

    async def habitat(self):
        """Module and group-wide warnings, for the habitat map: only always-shared group indicators, nothing private."""
        pb = await active_playbook(self.env)
        st = self._status(pb, self._load_state())
        own = [a for a in (st["alerts"] if st else []) if pb.domains[a["domain"]].shared_by_group]
        return {"module": self._load_state().get("module"), "own": own,
                "prewarned": [c for c in (st["crew_alerts"] if st else []) if c.get("prewarn")]}  # fmt: skip

    async def _with_history(self, pb, entity_id, state, ts):
        """Once per mission day: seed missing baselines and refresh chronic trends from 90 days of Tiger Data history."""
        day = ts // 86_400_000
        if not pb or state.get("history_day") == day:
            return
        try:
            daily = await tiger_history(self.env, entity_id, 90)
        except Exception as e:  # noqa: BLE001 - the engine works without history, from live readings alone
            print(f"tiger history failed: {e}")
            return
        state["history_day"] = day
        engine.seed_baselines(pb, state, daily)
        state["chronic"] = engine.chronic_trends(pb, daily)

    async def checkin(self, entity_id, readings):
        """Self-reported readings. Stamped with the mission clock, the newest sensor time this astronaut has sent."""
        # shortcut: mission time is whatever the data stream says, switch to wall clock with live sensors
        ts = self._load_state().get("clock") or int(time.time() * 1000)
        await self.ingest(entity_id, [{**r, "ts": ts} for r in readings])
        return ts

    async def ingest(self, entity_id, readings):
        """Called by the queue consumer with one chunk of this astronaut's readings."""
        pb = await active_playbook(self.env)
        state = self._load_state()
        await self._with_history(pb, entity_id, state, max(r["ts"] for r in readings))
        since = state.get("clock") or min(r["ts"] for r in readings) - 1
        state["clock"] = max(state.get("clock", 0), max(r["ts"] for r in readings))
        state["module"] = next((r["meta"]["module"] for r in readings if (r.get("meta") or {}).get("module")), state.get("module"))
        triggers = []
        if pb and any(rule.when.type == "donki" for rule in pb.rules) and state["clock"] > since:
            # DONKI events that happened between the last mission time and now, in time order with the readings.
            # Only months already loaded by the cron or the Space Weather view are seen.
            res = await self.env.DB.prepare(DONKI_TRIGGERS).bind(since, state["clock"], since, state["clock"]).all()
            window = [t for t in space.triggers([json.loads(x["data"]) for x in res["results"]]) if since < t["ts"] <= state["clock"]]
            triggers = [(t["ts"], 0, t) for t in window]
        events = []
        newest = {}
        for ts, is_reading, item in sorted(triggers + [(r["ts"], 1, r) for r in readings], key=lambda x: (x[0], x[1])):
            if not is_reading:
                events += engine.donki_step(pb, state, item)
                continue
            r = item
            if pb:
                events += engine.step(pb, state, r)
            k = (r["domain"], r["metric"])
            if k not in newest or r["ts"] >= newest[k]["ts"]:
                newest[k] = r
        rows = list(newest.values())

        db = self.env.DB
        stmts = [
            db.prepare(UPSERT_D1).bind(
                entity_id, r["domain"], r["metric"], r["value"], r.get("unit"), r.get("source"), r["ts"]
            )
            for r in rows
        ]
        stmts.append(db.prepare(UPSERT_CREW).bind(entity_id, max(r["ts"] for r in rows), state.get("module")))
        for e in events:
            a = e["alert"]
            alert_id = f'{entity_id}:{a["id"]}'
            if e["type"] == "fired":
                stmts.append(
                    db.prepare(INSERT_ALERT).bind(
                        alert_id, entity_id, a["rule"], a["domain"], a["metric"], a["severity"], a["message"],
                        a["value"], a["baseline"], json.dumps(a), f"{pb.name}@{pb.version}", a["ts"],
                    )
                )  # fmt: skip
            else:
                stmts.append(db.prepare("UPDATE alerts SET cleared_ts = ? WHERE id = ?").bind(e["ts"], alert_id))
        await db.batch(stmts)

        status = self._status(pb, state)
        out = json.dumps({"type": "indicators", "entity_id": entity_id, "readings": rows, "status": status})
        choices = self._choices()
        earth_rows, earth_status = engine.for_earth(pb, choices, rows, status)
        # Dual timelines: the crew member is guided now, Earth gets the same message one comm delay later.
        # The crew is told before the ledger write, so a ledger failure never holds back an alert.
        for s in self.ctx.getWebSockets("crew"):
            s.send(out)
        for e in events:
            await self._tell_crew(pb, entity_id, state.get("module"), e)
            if e["type"] == "fired":
                await self._log_alert(entity_id, e["alert"], engine.alert_open(pb, e["alert"]["domain"], e["alert"]["metric"]))
                if e["alert"]["severity"] == "critical" and e["alert"].get("checklist"):
                    await start_incident(self.env, entity_id, f'{entity_id}:{e["alert"]["id"]}', e["alert"])
        # Saved only after D1 and the ledger accepted: if either fails, the queue retries from the old state,
        # and the ledger keys return the entries already written instead of duplicating them.
        self._put("state", state)
        # Demo: the black-box head travels with the message, so mission control sees entries only once they reach Earth.
        head = await ledger_stub(self.env).head() if demo_mode(self.env) else None
        earth_out = json.dumps({"type": "indicators", "entity_id": entity_id, "readings": earth_rows, "status": earth_status,
                                "withheld": engine.withheld(pb, choices), "ledger_seq": head["seq"] if head else None})  # fmt: skip
        fired = any(e["type"] == "fired" for e in events)
        await self._send_to_earth(earth_out, await comm_delay(self.env, state["clock"]), alert=fired)
        return len(readings)

    async def _log_alert(self, entity_id, a, shared=True):
        """Black box: the alert, then what the edge did about it without waiting for Earth.

        A private-level alert is logged sealed: the log shows that it happened, not what it was. The flight surgeon gets it through the shared view.
        """
        alert_id = f'{entity_id}:{a["id"]}'
        crew = {"self": "", "group": "alerted this module", "all": "alerted the whole crew"}.get(a.get("alert_crew"), "")
        done = [
            *([f'showed checklist {a["checklist"]}'] if a.get("checklist") else []),
            *([crew] if crew else []),
            *(f"paged {r}" for r in a.get("paged", [])),
            *(f"notified {r}" for r in a.get("notified", [])),
        ]
        held = ", ".join(" ".join(str(v) for v in q.values()).replace("_", " ") for q in a.get("queued", []))
        entries = [
            ("alert", a["message"], "A private alert fired.", {"alert_id": alert_id, **a}, "alert"),
            *([("autonomous_action", f'Edge acted on "{a["message"]}": {", ".join(done)}.', "Edge acted on a private alert.",
                {"alert_id": alert_id, "actions": done}, "actions")] if done else []),
            *([("earth_review", f'Waiting for Earth on "{a["message"]}": {held}.', "A private alert is waiting for Earth.",
                {"alert_id": alert_id, "queued": a["queued"]}, "queued")] if held else []),
        ]  # fmt: skip
        for kind, summary, private_summary, payload, key in entries:
            if not shared:
                summary, payload = f"{private_summary} Only the crew member can see it.", ledger.sealed(payload)
            await ledger_log(self.env, kind, summary, payload, entity_id, key=f"{key}:{alert_id}")

    async def ping(self):
        sql = self.ctx.storage.sql
        sql.exec("CREATE TABLE IF NOT EXISTS counter (id INTEGER PRIMARY KEY, n INTEGER)")
        row = sql.exec(
            "INSERT INTO counter VALUES (1, 1) "
            "ON CONFLICT (id) DO UPDATE SET n = n + 1 RETURNING n"
        ).one()
        return row.n

    async def fetch(self, request):
        q = parse_qs(urlparse(request.url).query)
        # "surgeon" and "limited" are set by Default.socket from the verified role; the crew member's own copy counts as surgeon.
        tags = ["crew"] if q.get("as") != ["earth"] else ["earth", "surgeon" if q.get("role") == ["surgeon"] else "limited"]
        client, server = WebSocketPair.new().object_values()
        self.ctx.acceptWebSocket(server, to_js(tags))  # hibernatable: no cost while idle
        return Response(None, status=101, web_socket=client)

    async def webSocketMessage(self, ws, message):
        sockets = self.ctx.getWebSockets()
        out = json.dumps({"echo": str(message), "connections": len(sockets)})
        for s in sockets:
            s.send(out)

    async def webSocketClose(self, ws, code, reason, was_clean):
        # 1005/1006 etc. are reserved: received, never sendable. close() accepts only 1000 or 3000-4999.
        ws.close(code if code == 1000 or 3000 <= code <= 4999 else 1000, reason)


INSERT_LEDGER = (
    "INSERT OR IGNORE INTO ledger (seq, hash, prev_hash, type, entity_id, timestamp, summary, reviewed_seq) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)


class Ledger(DurableObject):
    """The only writer of the black-box log. One instance, "main".

    Its own SQLite is the record of appends: seq and prev_hash are assigned and the entry is stored
    with no await in between, so two appends can never read the same head and fork the chain.
    R2 and the D1 index are copies made afterwards; an alarm retries any copy that failed.
    """

    def _sql(self):
        sql = self.ctx.storage.sql
        sql.exec("CREATE TABLE IF NOT EXISTS entries (seq INTEGER PRIMARY KEY, key TEXT UNIQUE, body TEXT NOT NULL, copied INTEGER NOT NULL DEFAULT 0)")
        sql.exec("CREATE TABLE IF NOT EXISTS tampered (seq INTEGER PRIMARY KEY)")
        sql.exec("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
        return sql

    def _chain(self, sql):
        """This log's R2 prefix under ledger/. Empty for a log started before chains were named."""
        rows = [r.v for r in sql.exec("SELECT v FROM meta WHERE k = 'chain'")]
        return rows[0] if rows else ""

    def _last(self, sql):
        rows = [r.body for r in sql.exec("SELECT body FROM entries ORDER BY seq DESC LIMIT 1")]
        return json.loads(rows[0]) if rows else None

    def _insert(self, sql, fields):
        last = self._last(sql)
        seq, prev = (last["seq"] + 1, last["hash"]) if last else (0, ledger.GENESIS_PREV)
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        entry = ledger.make_entry(seq, prev, fields, now)
        sql.exec("INSERT INTO entries (seq, key, body) VALUES (?, ?, ?)", seq, fields.get("key") or f"seq:{seq}", ledger.canonical(entry).decode())
        return entry

    async def append(self, fields_json):
        fields = json.loads(fields_json)
        sql = self._sql()
        # Synchronous from here to the last insert: nothing else runs in this object meanwhile.
        if not self._last(sql):
            g = self._insert(sql, {"type": "genesis", "summary": "Black-box log started.", "actor": "edge-system", "key": "genesis"})
            sql.exec("INSERT OR REPLACE INTO meta VALUES ('chain', ?)", g["hash"][:16])
        found = [r.body for r in sql.exec("SELECT body FROM entries WHERE key = ?", fields["key"])] if fields.get("key") else []
        entry = json.loads(found[0]) if found else self._insert(sql, fields)
        await self._copy_pending()
        return {"entry": entry, "created": not found}

    async def _copy_pending(self):
        sql = self._sql()
        chain = self._chain(sql)
        for seq, body in [(r.seq, r.body) for r in sql.exec("SELECT seq, body FROM entries WHERE copied = 0 ORDER BY seq")]:
            e = json.loads(body)
            try:
                key = ledger.r2_key(seq, chain)
                try:
                    await self.env.BUCKET.put(key, body)
                except Exception:
                    # A retry after the put landed but the D1 copy failed: the lock refuses the second put.
                    old = await self.env.BUCKET.get(key)
                    if not old or await old.text() != body:
                        raise
                await self.env.DB.prepare(INSERT_LEDGER).bind(
                    seq, e["hash"], e["prev_hash"], e["type"], e["entity_id"], e["timestamp"], e["summary"],
                    e["payload"].get("reviewed_seq"),
                ).run()  # fmt: skip
            except Exception as err:  # noqa: BLE001 - the entry is safe in this object; retry the copy later
                print(f"ledger copy of seq {seq} failed: {err}")
                await self.ctx.storage.setAlarm(int(time.time() * 1000) + 10_000)
                return
            sql.exec("UPDATE entries SET copied = 1 WHERE seq = ?", seq)

    async def alarm(self, *_):
        await self._copy_pending()

    async def head(self):
        """The newest entry whose copies are all stored: what verify can check up to. None if the log is empty."""
        sql = self._sql()
        rows = [r.body for r in sql.exec("SELECT body FROM entries WHERE seq < (SELECT coalesce(min(seq), 1e18) FROM entries WHERE copied = 0) ORDER BY seq DESC LIMIT 1")]
        if not rows:
            return None
        e = json.loads(rows[0])
        pending = sql.exec("SELECT count(*) AS n FROM entries WHERE copied = 0").one().n
        tampered = [r.seq for r in sql.exec("SELECT seq FROM tampered")]
        return {"seq": e["seq"], "hash": e["hash"], "pending": pending, "chain": self._chain(sql), "tampered": tampered}

    async def prev_hash_of(self, seq):
        """The prev_hash this object recorded for `seq`: the anchor for a verify window that starts there."""
        rows = [r.body for r in self._sql().exec("SELECT body FROM entries WHERE seq = ?", seq)]
        return json.loads(rows[0])["prev_hash"] if rows else ledger.GENESIS_PREV

    async def demo_tamper(self, seq):
        """Demo only: change one stored R2 entry's summary and leave its hash alone. -1 means the newest entry."""
        sql = self._sql()
        q = "SELECT seq, body FROM entries WHERE copied = 1 " + ("ORDER BY seq DESC LIMIT 1" if seq < 0 else "AND seq = ?")
        rows = [(r.seq, r.body) for r in (sql.exec(q) if seq < 0 else sql.exec(q, seq))]
        if not rows:
            return {"error": "no stored entry with that seq"}
        seq, body = rows[0]
        e = json.loads(body)
        e["summary"] += " [edited after the fact]"
        edited = ledger.canonical(e).decode()
        key = ledger.r2_key(seq, self._chain(sql))
        refused = {}
        for op, attempt in (("overwrite", lambda: self.env.BUCKET.put(key, edited)), ("delete", lambda: self.env.BUCKET.delete(key))):
            try:
                await attempt()
                refused[op] = None
            except Exception as err:  # noqa: BLE001 - the refusal is the point
                refused[op] = str(err)[:200]
        if not all(refused.values()):
            # No lock rule (local dev): the real copy changed. Put it back and say so instead of pretending.
            await self.env.BUCKET.put(key, body)
        await self.env.BUCKET.put(ledger.demo_key(seq, self._chain(sql)), edited)
        sql.exec("INSERT OR IGNORE INTO tampered (seq) VALUES (?)", seq)
        return {"tampered": seq, "key": key, "refused": refused, "locked": all(refused.values())}

    async def demo_restore(self):
        """Demo only: drop every demo-only tampered copy, so verify reads the locked originals again."""
        sql = self._sql()
        restored = []
        for seq in [r.seq for r in sql.exec("SELECT seq FROM tampered")]:
            await self.env.BUCKET.delete(ledger.demo_key(seq, self._chain(sql)))
            sql.exec("DELETE FROM tampered WHERE seq = ?", seq)
            restored.append(seq)
        return {"restored": restored}

    async def demo_reset(self):
        """Demo only: forget the log. Its locked R2 copies stay under their chain prefix, which R2 will not delete;
        the next append starts a new chain at genesis under a new prefix."""
        await self.demo_restore()
        await self.ctx.storage.deleteAlarm()
        await self.ctx.storage.deleteAll()


CRON_MAINTENANCE = "17 */6 * * *"  # DONKI refresh and chain verify
CRON_REMINDER = "0 14 * * *"  # daily
# All three must match wrangler.jsonc triggers.crons: tests/test_crons.py checks it.
CRON_REPORT = "0 6 * * 1"  # Mondays
DAY_MS = 86_400_000


async def remind_checkins(env):
    """Mark a check-in reminder due for every crew member with no check-in in the last 24 h (wall clock)."""
    now = int(time.time() * 1000)
    crew = (await env.DB.prepare("SELECT entity_id FROM crew").all())["results"]
    for r in crew:
        last = await env.DB.prepare("SELECT max(created_at) AS at FROM checkins WHERE entity_id = ?").bind(r["entity_id"]).first()
        if (last["at"] or 0) < now - DAY_MS:
            await env.DB.prepare("INSERT OR REPLACE INTO settings (k, v) VALUES (?, ?)").bind(f"reminder:{r['entity_id']}", str(now)).run()


async def write_reports(env):
    """One markdown report per crew member for the 7 days up to their newest reading, saved to R2 (reports/<id>/<week>.md)."""
    pb = await active_playbook(env)
    labels = {f"{d}/{i}": (s.label, s.unit or "") for d, dom in (pb.domains.items() if pb else []) for i, s in dom.indicators.items()}
    crew = (await env.DB.prepare("SELECT entity_id FROM crew").all())["results"]
    for r in crew:
        e = r["entity_id"]
        end = (await env.DB.prepare("SELECT max(ts) AS ts FROM latest WHERE entity_id = ?").bind(e).first())["ts"]
        if not end:
            continue
        start = end - 7 * DAY_MS
        try:
            daily = [d for d in await tiger_history(env, e, 7) if d["day"] > start - DAY_MS]
        except Exception as ex:  # noqa: BLE001 - a report without readings is still worth saving
            print(f"report history failed: {ex}")
            daily = []
        alerts = (await env.DB.prepare("SELECT severity, message, fired_ts FROM alerts WHERE entity_id = ? AND fired_ts > ?").bind(e, start).all())["results"]
        days = await env.DB.prepare("SELECT count(DISTINCT ts / ?) AS n FROM checkins WHERE entity_id = ? AND ts > ?").bind(DAY_MS, e, start).first()
        md = report.weekly_report(e, start, end, _py(daily), _py(alerts), days["n"], labels)
        week = datetime.fromtimestamp(end / 1000, timezone.utc).strftime("%G-W%V")
        await env.BUCKET.put(f"reports/{e}/{week}.md", md)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = urlparse(request.url).path
        if path.startswith("/ws/"):
            return await self.socket(request, unquote(path[4:]))
        return await asgi.fetch(app, request, self.env, self.ctx)

    async def socket(self, request, entity_id):
        """A crew socket carries private live data: only that crew member. An Earth socket: mission control too."""
        js = request.js_object
        try:
            who = await authenticate(self.env, js.headers)
        except ValueError as e:
            return Response(str(e), status=401)
        earth = parse_qs(urlparse(js.url).query).get("as") == ["earth"]
        demo_crew = crew_sim.CREW if demo_mode(self.env) else ()
        if not ((earth and who["role"] in auth.MISSION) or auth.acts_as(who, entity_id, demo_crew)):
            return Response("this socket is not yours", status=403)
        if not earth:
            return await self.env.ASTRONAUT.getByName(entity_id).fetch(js)
        # The role tag comes from the verified identity, never from the client's query.
        surgeon = who["role"] == "flight_surgeon" or auth.acts_as(who, entity_id)
        query = {k: v for k, v in parse_qs(urlparse(js.url).query).items() if k != "role"}
        url = urlparse(js.url)._replace(query=urlencode({**{k: v[0] for k, v in query.items()}, **({"role": "surgeon"} if surgeon else {})}))
        return await self.env.ASTRONAUT.getByName(entity_id).fetch(JsRequest.new(url.geturl(), js))

    async def scheduled(self, controller, env, ctx):
        """Cron. Daily: check-in reminders. Weekly: health reports. Otherwise: DONKI refresh and chain verify."""
        if controller.cron == CRON_REMINDER:
            return await remind_checkins(self.env)
        if controller.cron == CRON_REPORT:
            return await write_reports(self.env)
        if controller.cron != CRON_MAINTENANCE:
            print(f"scheduled: unknown cron {controller.cron!r}, skipped")  # never run DONKI and verify for a typo
            return
        # Every 6 h: keep DONKI fresh. This month and last month are re-fetched, because DONKI revises recent events.
        today = datetime.now(timezone.utc).date()
        recent = months_between(today - timedelta(days=31), today)
        window = months_between(date.fromisoformat(self.env.DONKI_START), date.fromisoformat(self.env.DONKI_END))
        for month in dict.fromkeys(window + recent):
            await asyncio.gather(*(load_month(self.env, kind, month, refresh=month in recent) for kind in space.KINDS))
        # Black box: re-verify the chain, then record the result and the head as a checkpoint.
        result = await verify_chain(self.env)
        print(f"ledger verify: {result}")
        verdict = "passed" if result["ok"] else f"FAILED, {result['reason']}"
        await ledger_log(
            self.env, "checkpoint", f"Scheduled verify {verdict} ({result['checked']} entries checked).",
            {"verify": {k: v for k, v in result.items() if k != "head"}, "head": result["head"]},
        )  # fmt: skip

    async def queue(self, batch, *_):  # runtime also passes env and ctx
        by_entity = {}
        for msg in batch.messages:
            body = msg.body
            if body["readings"]:
                await self.env.ASTRONAUT.getByName(body["entity_id"]).ingest(body["entity_id"], body["readings"])
                by_entity.setdefault(body["entity_id"], []).extend(_py(body["readings"]))
            msg.ack()  # an exception above leaves the message unacked, so the queue retries it
        await tiger_insert(self.env, by_entity)  # the whole batch in one insert
        await count_queue(self.env, "q_done", len(batch.messages))

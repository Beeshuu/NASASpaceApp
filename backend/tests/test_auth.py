"""Access JWT claims and role rules self-check. Run: uv run python tests/test_auth.py"""

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import auth  # noqa: E402

TEAM, AUD, NOW = "https://vop.cloudflareaccess.com", "aud-tag", 1_800_000_000


def b64(obj):
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


def claims(**over):
    base = {"iss": TEAM, "aud": [AUD], "exp": NOW + 600, "nbf": NOW - 10, "sub": "u1", "email": "a@b.c", "custom": {}}
    return {k: v for k, v in {**base, **over}.items() if v is not None}


def refused(payload):
    try:
        auth.identity(payload, TEAM, AUD, NOW)
    except ValueError:
        return True
    return False


# Token checks
assert refused(claims(iss="https://evil.cloudflareaccess.com"))
assert refused(claims(aud=["other"]))
assert refused(claims(exp=NOW - 120))
assert refused(claims(exp=None))
assert refused(claims(nbf=NOW + 120))
assert refused(claims(email=None))
assert not refused(claims(aud=AUD))  # a single string audience is valid too
assert auth.identity(claims(), TEAM + "/", AUD, NOW)  # trailing slash on the configured team domain

# Roles come only from the namespaced Auth0 claim, and only known roles count
crew = auth.identity(claims(custom={f"{auth.CLAIM}role": "crew", f"{auth.CLAIM}crew_id": "okafor"}), TEAM, AUD, NOW)
assert crew == {"email": "a@b.c", "role": "crew", "crew_id": "okafor", "actor": "a@b.c"}, crew
assert auth.identity(claims(custom={f"{auth.CLAIM}role": "admin"}), TEAM, AUD, NOW)["role"] is None
assert auth.identity(claims(custom={"role": "commander"}), TEAM, AUD, NOW)["role"] is None
surgeon = auth.identity(claims(custom={f"{auth.CLAIM}role": "flight_surgeon", f"{auth.CLAIM}crew_id": "okafor"}), TEAM, AUD, NOW)
assert surgeon["crew_id"] is None  # only crew own an entity

# Service token: no email, no role
svc = auth.identity(claims(sub="", email=None, common_name="abc.access"), TEAM, AUD, NOW)
assert svc == {"email": None, "role": None, "crew_id": None, "actor": "service:abc.access"}, svc

# Who may act as a crew member
commander = {"role": "commander", "crew_id": None}
assert auth.acts_as(crew, "okafor") and not auth.acts_as(crew, "reyes")
assert not auth.acts_as(commander, "okafor")
assert auth.acts_as(commander, "okafor", {"okafor": "hab-a"})  # demo mode only
assert not auth.acts_as({**crew, "crew_id": None}, "")  # a crew account with no crew id owns nothing
assert not auth.acts_as(svc, "okafor", {"okafor": "hab-a"})

# Parsing
h, p, signed, sig = auth.split(f"{b64({'alg': 'RS256', 'kid': 'k'})}.{b64({'a': 1})}.c2ln")
assert h["kid"] == "k" and p == {"a": 1} and sig == b"sig" and signed.count(b".") == 1
for bad in ("a.b", f"{b64({'alg': 'none'})}.{b64({})}.", f"{b64({'alg': 'HS256'})}.{b64({})}.c2ln", "!!.??.zz"):
    try:
        auth.split(bad)
        raise AssertionError(f"accepted {bad}")
    except ValueError:
        pass

assert auth.cookie("a=1; CF_Authorization=tok; b=2", "CF_Authorization") == "tok"
assert auth.cookie(None, "CF_Authorization") is None
try:
    auth.dev_identity("admin", None)
    raise AssertionError("accepted an unknown dev role")
except ValueError:
    pass

# Guests: only the exact configured hostname, never when it is unset.
assert auth.is_guest_host("guest.vitalorbit.health", "guest.vitalorbit.health")
assert auth.is_guest_host("Guest.VitalOrbit.health:443", "guest.vitalorbit.health")
assert not auth.is_guest_host("vitalorbit.health", "guest.vitalorbit.health")
assert not auth.is_guest_host("guest.vitalorbit.health.evil.com", "guest.vitalorbit.health")
assert not auth.is_guest_host("guest.vitalorbit.health", None) and not auth.is_guest_host(None, "")
assert auth.guest_identity()["guest"] and auth.guest_identity()["actor"] == "guest"

print("auth ok")

# A guest picks a role on the demo page. Anything unknown falls back to the commander, or to the first simulated crew member.
CREW = ("okafor", "reyes")
assert auth.guest_identity("crew", "reyes", CREW)["crew_id"] == "reyes"
assert auth.guest_identity("crew", "mallory", CREW)["crew_id"] == "okafor", "only the simulated crew"
assert auth.guest_identity("flight_surgeon", "reyes", CREW) == {**auth.guest_identity(), "role": "flight_surgeon"}
assert auth.guest_identity("admin")["role"] == "commander" and auth.guest_identity(None)["crew_id"] is None
assert auth.acts_as(auth.guest_identity("crew", "reyes", CREW), "reyes") and not auth.acts_as(auth.guest_identity("crew", "reyes", CREW), "okafor")

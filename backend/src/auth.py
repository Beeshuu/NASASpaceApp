"""Who is calling: Cloudflare Access JWT claims and the role rules.

Pure Python with no Workers imports, so it runs under plain CPython for tests. main.py checks the RS256
signature with WebCrypto; everything else about the token is checked here.
"""

import base64
import json

ROLES = frozenset({"crew", "flight_surgeon", "commander"})
MISSION = frozenset({"flight_surgeon", "commander"})  # see mission control and review the black box
CLAIM = "https://vitalorbit.health/"  # namespace of the Auth0 claims; auth0/post-login.js sets them
LEEWAY_S = 60  # clock skew allowed on exp and nbf


def b64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def split(token: str):
    """(header, payload, signed bytes, signature). Raises ValueError for anything that is not a JWT."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("not a JWT")
    try:
        header, payload = json.loads(b64url(parts[0])), json.loads(b64url(parts[1]))
        sig = b64url(parts[2])
    except (ValueError, TypeError) as e:
        raise ValueError(f"malformed JWT: {e}") from None
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise ValueError("malformed JWT")
    if header.get("alg") != "RS256":
        raise ValueError("JWT must be RS256")
    return header, payload, f"{parts[0]}.{parts[1]}".encode(), sig


def identity(payload: dict, team_domain: str, aud: str, now: float) -> dict:
    """The caller, from a signature-checked Access JWT payload. Raises ValueError if the token is not for us.

    {"email", "role", "crew_id", "actor"}. A service token has no email and no role: it can only reach routes
    that need no role, such as keyed ingest. An Auth0 user without a known role gets role None.
    """
    if payload.get("iss") != team_domain.rstrip("/"):
        raise ValueError("wrong issuer")
    auds = payload.get("aud")
    if aud not in (auds if isinstance(auds, list) else [auds]):
        raise ValueError("wrong audience")
    if not isinstance(payload.get("exp"), (int, float)) or payload["exp"] + LEEWAY_S < now:
        raise ValueError("expired")
    if payload.get("nbf", 0) - LEEWAY_S > now:
        raise ValueError("not valid yet")
    if not payload.get("sub") and payload.get("common_name"):
        return {"email": None, "role": None, "crew_id": None, "actor": f"service:{payload['common_name']}"}
    email = payload.get("email")
    if not email:
        raise ValueError("no email")
    custom = payload.get("custom") or {}
    role = custom.get(f"{CLAIM}role")
    role = role if role in ROLES else None
    crew_id = custom.get(f"{CLAIM}crew_id") if role == "crew" else None
    return {"email": email, "role": role, "crew_id": crew_id or None, "actor": email}


def guest_identity(role: str | None = None, crew_id: str | None = None, crew=()) -> dict:
    """Judges and visitors on the public guest hostname, without an account.

    `role`, `crew_id`: what the visitor picked on the demo page. Anything else falls back to the commander, and to
    the first of `crew`, the simulated crew a guest may act as. main.py refuses guests the routes that change the
    mission for everyone else (no_guest).
    """
    role = role if role in ROLES else "commander"
    if role == "crew":
        crew_id = crew_id if crew_id in crew else next(iter(crew), None)
    return {"email": None, "role": role, "crew_id": crew_id if role == "crew" else None, "actor": "guest", "guest": True}


def is_guest_host(host: str | None, guest_host: str | None) -> bool:
    """Only the configured guest hostname, compared without port and case. Unset means no guest access at all."""
    return bool(guest_host) and (host or "").split(":")[0].lower() == guest_host.lower()


def dev_identity(role: str, crew_id: str | None) -> dict:
    """Local development without Access: the identity .dev.vars names."""
    if role not in ROLES:
        raise ValueError(f"DEV_ROLE must be one of {sorted(ROLES)}")
    return {"email": "dev@localhost", "role": role, "crew_id": crew_id if role == "crew" else None, "actor": f"dev:{role}"}


def acts_as(who: dict, entity_id: str, demo_crew=()) -> bool:
    """May `who` read and write `entity_id`'s private crew data? Only that crew member.

    `demo_crew`: in demo mode, the simulated crew the commander may act as, so /demo works after one login.
    """
    return (who["role"] == "crew" and who["crew_id"] == entity_id) or (who["role"] == "commander" and entity_id in demo_crew)


def cookie(header: str | None, name: str):
    for part in (header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return None

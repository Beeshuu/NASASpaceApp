"""Black-box decision log: canonical entries, hashes and chain checks.

Pure Python with no Workers imports, so it runs under plain CPython for tests.
The Ledger Durable Object in main.py is the only code that appends.
"""

import hashlib
import json
import math

GENESIS_PREV = "0" * 64
TYPES = frozenset(
    {
        "alert",
        "recommendation",
        "checklist_step",
        "autonomous_action",
        "earth_review",  # actions the playbook holds for Earth instead of running at the edge
        "data_share",  # a crew member started or stopped sharing an indicator with Earth
        "review_approve",
        "review_override",
        "playbook_switch",
        "genesis",
        "checkpoint",  # cron verify result and the head at that time
        "pre_warn",  # a group-shared indicator breached and the other crew in the module were warned
        "workflow_step",  # one step of the incident-response Workflow
    }
)
REVIEWABLE = frozenset({"alert", "recommendation", "autonomous_action", "earth_review"})
OPTIONAL = ("entity_id", "actor", "playbook_name", "playbook_hash")


def r2_key(seq: int, chain: str = "") -> str:
    """The locked R2 copy. `chain` names one log since its genesis; "" is the log from before chains were named.

    The bucket's lock rule on ledger/ refuses every overwrite and delete, so a demo reset starts a new chain
    under its own prefix instead of reusing keys it can no longer touch.
    """
    return f"ledger/{chain}/{seq:08d}.json" if chain else f"ledger/{seq:08d}.json"


def demo_key(seq: int, chain: str = "") -> str:
    """Demo only: the tampered copy verify reads instead of the locked one. Outside ledger/, so it is not locked."""
    return f"demo-tamper/{chain or 'legacy'}/{seq:08d}.json"


def _finite(obj):
    """NaN and infinity become null: JSON cannot hold them, and one bad reading must not block the log."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_finite(v) for v in obj]
    return obj


def canonical(obj) -> bytes:
    """Sorted keys, no whitespace, UTF-8. NaN and infinity are refused: they are not JSON."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def entry_hash(entry: dict) -> str:
    return hashlib.sha256(canonical({k: v for k, v in entry.items() if k != "hash"})).hexdigest()


def sealed(payload) -> dict:
    """Stands in for a private payload: its fingerprint proves later what was logged, without showing it now."""
    return {"private": True, "content_sha256": hashlib.sha256(canonical(_finite(payload))).hexdigest()}


def make_entry(seq: int, prev_hash: str, fields: dict, timestamp: str) -> dict:
    if fields.get("type") not in TYPES:
        raise ValueError(f"unknown ledger entry type {fields.get('type')!r}")
    entry = {
        "seq": seq,
        "timestamp": timestamp,
        "type": fields["type"],
        "summary": str(fields.get("summary") or ""),
        # A JSON round trip copies the payload and makes what is hashed exactly what is stored.
        "payload": json.loads(canonical(_finite(fields.get("payload") or {}))),
        "prev_hash": prev_hash,
        **{k: fields.get(k) for k in OPTIONAL},
    }
    entry["hash"] = entry_hash(entry)
    return entry


def verify_entries(entries, start_seq: int = 0, prev_hash: str = GENESIS_PREV) -> dict:
    """Check entries in seq order from `start_seq`, whose prev_hash must be `prev_hash`.

    `None` stands for an entry whose stored copy is missing; anything not a dict for one that is not a JSON object.
    """
    checked = 0

    def bad(seq, reason):
        return {"ok": False, "checked": checked, "first_bad_seq": seq, "reason": f"{reason} at seq {seq}"}

    for expected, e in enumerate(entries, start_seq):
        checked += 1
        if e is None:
            return bad(expected, "missing entry")
        if not isinstance(e, dict):
            return bad(expected, "unreadable entry")
        if e.get("seq") != expected:
            return bad(e.get("seq"), "seq gap")
        if e.get("prev_hash") != prev_hash:
            return bad(expected, "broken link")
        if e.get("hash") != entry_hash(e):
            return bad(expected, "hash mismatch")
        prev_hash = e["hash"]
    return {"ok": True, "checked": checked, "first_bad_seq": None, "reason": None}

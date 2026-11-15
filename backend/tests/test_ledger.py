"""Ledger chain self-check. Run: uv run python tests/test_ledger.py"""

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

import ledger  # noqa: E402

T = "2026-11-14T00:00:00Z"


def chain(n):
    """Genesis plus n alert entries, linked."""
    out = [ledger.make_entry(0, ledger.GENESIS_PREV, {"type": "genesis", "summary": "chain start"}, T)]
    for i in range(1, n + 1):
        out.append(ledger.make_entry(i, out[-1]["hash"], {"type": "alert", "summary": f"alert {i}", "entity_id": "okafor"}, T))
    return out


# Canonical JSON: sorted keys, no spaces, UTF-8, non-ASCII kept as is.
assert ledger.canonical({"b": 1, "a": "é"}) == '{"a":"é","b":1}'.encode()

# Every entry carries exactly the spec's fields, and the hash covers all but itself.
e = chain(0)[0]
assert set(e) == {"seq", "timestamp", "type", "entity_id", "actor", "summary", "payload", "playbook_name", "playbook_hash", "prev_hash", "hash"}
assert e["prev_hash"] == "0" * 64 and e["payload"] == {} and e["entity_id"] is None
assert e["hash"] == ledger.entry_hash(e) == ledger.entry_hash({k: v for k, v in e.items() if k != "hash"})

# An intact chain passes.
assert ledger.verify_entries(chain(3)) == {"ok": True, "checked": 4, "first_bad_seq": None, "reason": None}
assert ledger.verify_entries([]) == {"ok": True, "checked": 0, "first_bad_seq": None, "reason": None}

# Editing a summary without updating the hash is caught at that seq.
c = chain(3)
c[2]["summary"] = "edited"
assert ledger.verify_entries(c) == {"ok": False, "checked": 3, "first_bad_seq": 2, "reason": "hash mismatch at seq 2"}

# Re-hashing the edited entry breaks the next link instead.
c[2]["hash"] = ledger.entry_hash(c[2])
r = ledger.verify_entries(c)
assert (r["first_bad_seq"], r["reason"]) == (3, "broken link at seq 3"), r

# A missing R2 object and a seq jump are named too.
c = chain(3)
c[2] = None
assert ledger.verify_entries(c)["reason"] == "missing entry at seq 2"
c = chain(3)
del c[2]
assert ledger.verify_entries(c)["reason"] == "seq gap at seq 3"

# Unknown types are refused.
try:
    ledger.make_entry(1, "0" * 64, {"type": "nope", "summary": "x"}, T)
except ValueError:
    pass
else:
    raise AssertionError("unknown type was accepted")

# Copies are independent: make_entry must not keep a reference to the caller's payload.
p = {"a": 1}
e = ledger.make_entry(1, "0" * 64, {"type": "alert", "summary": "x", "payload": p}, T)
p["a"] = 2
assert e["hash"] == ledger.entry_hash(copy.deepcopy(e)) and e["payload"] == {"a": 1}

# Verify can start mid-chain, anchored on the prev_hash the Ledger holds for the first seq checked.
c = chain(5)
assert ledger.verify_entries(c[3:], start_seq=3, prev_hash=c[2]["hash"]) == {"ok": True, "checked": 3, "first_bad_seq": None, "reason": None}
c[4]["summary"] = "edited"
assert ledger.verify_entries(c[3:], start_seq=3, prev_hash=c[2]["hash"])["reason"] == "hash mismatch at seq 4"

# A stored object that is not a JSON object is named, not a crash.
c = chain(3)
c[1] = "unreadable"
assert ledger.verify_entries(c) == {"ok": False, "checked": 2, "first_bad_seq": 1, "reason": "unreadable entry at seq 1"}

# A non-finite number in a payload is stored as null rather than refusing the whole entry.
e = ledger.make_entry(1, "0" * 64, {"type": "alert", "summary": "x", "payload": {"value": float("nan"), "n": [float("inf"), 1.5]}}, T)
assert e["payload"] == {"value": None, "n": [None, 1.5]} and e["hash"] == ledger.entry_hash(e)

# Locked copies live under ledger/ (the R2 lock rule's prefix); demo tampered copies never do.
assert ledger.r2_key(7) == "ledger/00000007.json"
assert ledger.r2_key(7, "abc") == "ledger/abc/00000007.json"
assert not ledger.demo_key(7, "abc").startswith("ledger/") and not ledger.demo_key(7).startswith("ledger/")

print("ledger ok")

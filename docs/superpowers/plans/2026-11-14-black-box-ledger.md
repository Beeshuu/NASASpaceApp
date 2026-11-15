# Black-box Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A hash-chained, single-writer decision log with verify, review, tamper demo, cron checkpoint and UI.

**Architecture:** Pure hashing and chain checks live in `src/ledger.py` (CPython-testable). A `Ledger` Durable Object is the only writer: it assigns seq and prev_hash and stores each entry in its own SQLite with no await in between, then copies it to R2 (`ledger/{seq:08d}.json`) and a D1 index, retrying failed copies from an alarm. Worker routes and the Astronaut DO call it through `ledger_log()`.

**Tech Stack:** Python Workers (FastAPI via asgi), Durable Objects SQLite, R2, D1, React + Vite.

**Spec:** `docs/superpowers/specs/2026-11-14-black-box-ledger-design.md`

## Global Constraints

- Python, `hashlib` SHA-256. No new packages.
- Canonical JSON: `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`.
- `hash = sha256(canonical(entry without "hash")).hexdigest()`. Genesis: seq 0, `prev_hash = "0" * 64`.
- Entry fields exactly: `seq, timestamp, type, entity_id, actor, summary, payload, playbook_name, playbook_hash, prev_hash, hash`.
- Types: `alert, recommendation, checklist_step, autonomous_action, data_share, review_approve, review_override, playbook_switch, genesis, checkpoint`.
- `actor` is `"edge-system"`, the crew id, or `"mission-control"`, each with `# TODO(phase 13): Auth0 identity`.
- Never mutate or delete R2 ledger objects outside `demo_tamper` / `demo_restore`.
- Tamper verify reason text exactly: `hash mismatch at seq N`.

## Review Focus

1. Queue retry after an alert fires: the same alert must not be appended twice (idempotency key). Test in Task 1 (`append` dedup is in the DO, so Task 2 curl check re-posts a review and expects 409).
2. R2 object missing for a seq (copy failed, not yet retried): verify must say `missing entry at seq N`, not crash. Test in Task 1.
3. Empty chain (no entry yet): `GET /api/ledger` returns `[]` and verify returns `ok: true, checked: 0`. Task 2 curl check.
4. Review of an unknown seq, a non-reviewable type, or a second review: 404, 422, 409. Task 2 curl check.
5. Demo endpoints with `DEMO_MODE` unset: 404. Task 2 curl check.

---

### Task 1: Chain core

**Files:**
- Create: `src/ledger.py`
- Test: `tests/test_ledger.py` (assert script, same style as `tests/test_engine.py`, prints `ledger ok`)

**Interfaces:**
- Produces: `GENESIS_PREV: str`, `TYPES: frozenset[str]`, `REVIEWABLE = {"alert", "recommendation", "autonomous_action"}`,
  `canonical(obj) -> bytes`, `entry_hash(entry: dict) -> str` (ignores a `"hash"` key),
  `make_entry(seq: int, prev_hash: str, fields: dict, timestamp: str) -> dict` (fills missing optional fields with None, payload with `{}`, raises `ValueError` on unknown type),
  `verify_entries(entries: Iterable[dict | None]) -> dict` returning `{"ok", "checked", "first_bad_seq", "reason"}`; `None` in the iterable means the R2 object was missing.

- [ ] **Step 1: Write the failing test** covering: genesis + 3 entries verify `ok` with `checked == 4`; changing `summary` of seq 2 gives `{"ok": False, "first_bad_seq": 2, "reason": "hash mismatch at seq 2"}`; recomputing seq 2's hash after the edit gives `reason == "broken link at seq 3"`; a `None` at index 2 gives `"missing entry at seq 2"`; a seq jump gives `"seq gap at seq N"`; `canonical({"b": 1, "a": "é"}) == '{"a":"é","b":1}'.encode()`; `make_entry` with type `"nope"` raises `ValueError`.
- [ ] **Step 2: Run** `uv run python tests/test_ledger.py`. Expected: `ModuleNotFoundError: ledger`.
- [ ] **Step 3: Implement** `src/ledger.py`. Check order per entry: missing, seq continuity, prev link, hash.
- [ ] **Step 4: Run** `uv run python tests/test_ledger.py` and `uv run python tests/test_engine.py`. Expected: `ledger ok`, `engine ok`.

### Task 2: Ledger DO, storage, endpoints

**Files:**
- Create: `migrations/0006_ledger.sql`: `ledger (seq INTEGER PRIMARY KEY, hash TEXT NOT NULL, prev_hash TEXT NOT NULL, type TEXT NOT NULL, entity_id TEXT, timestamp TEXT NOT NULL, summary TEXT NOT NULL, reviewed_seq INTEGER)`, index on `(type)` and `(reviewed_seq)`.
- Modify: `wrangler.jsonc`: DO binding `LEDGER` -> class `Ledger`, migration tag `v2` with `new_sqlite_classes: ["Ledger"]`.
- Modify: `src/main.py`: `Ledger` DO class, `ledger_log`, routes, `BINDINGS` gains `LEDGER`.
- Modify: `.dev.vars.example`: `DEMO_MODE=` line with comment.

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `Ledger.append(fields: dict) -> dict` returning `{"entry": dict, "created": bool}`. `fields` may carry `key` (idempotency, stored in DO SQLite, not in the entry). Creates genesis first when the chain is empty. DO SQLite table `entries (seq INTEGER PRIMARY KEY, key TEXT UNIQUE, body TEXT NOT NULL, copied INTEGER NOT NULL DEFAULT 0)`. Seq, prev_hash and the insert happen with no await between them.
  - `Ledger.head() -> {"seq": int, "hash": str} | None`, `Ledger.demo_tamper(seq: int | None) -> int`, `Ledger.demo_restore() -> int | None`, `Ledger.alarm()` copies rows with `copied = 0`.
  - `async def ledger_log(env, type: str, summary: str, payload: dict, entity_id: str | None = None, actor: str = "edge-system", key: str | None = None) -> dict` in `main.py`; reads playbook name and sha from `active_playbook` / `_playbook_cache`.
  - Routes: `GET /api/ledger?limit=50&before=` (D1 index, newest first, max 200, response `{"entries": [...], "demo": bool}`), `GET /api/ledger/verify` (R2 in seq order, `VERIFY_MAX = 1000`, adds `"complete": bool`), `GET /api/ledger/entries/{seq}` (R2 body), `GET /api/ledger/queue` (reviewable, `reviewed_seq` not referenced), `POST /api/ledger/review/{seq}` body `{"decision": "approve" | "override", "note": str <= 500}`, `POST /api/ledger/demo/tamper` body `{"seq": int | null}`, `POST /api/ledger/demo/restore`.

- [ ] **Step 1: Implement** the migration, wrangler binding, DO and routes.
- [ ] **Step 2: Apply and restart.** `uv run pywrangler d1 migrations apply vital-orbit-pulse --local`, add `DEMO_MODE=1` to `.dev.vars`, restart dev.
- [ ] **Step 3: Curl checks.** Empty: `GET /api/ledger` -> `entries: []`; verify -> `ok: true, checked: 0`. Review seq 999 -> 404. With `DEMO_MODE` unset, tamper -> 404.

### Task 3: Hooks

**Files:** Modify `src/main.py` only.

- [ ] **Step 1: Alerts.** In `Astronaut.ingest`, after `db.batch` succeeds and before `self._put("state")`, for each fired event: `ledger_log(type="alert", key=f"alert:{alert_id}", entity_id, payload=alert dict incl. mission ts)`; when the alert has actions, also `type="autonomous_action", key=f"actions:{alert_id}"`, payload lists `checklist`, `alert_crew`, `paged`, `notified`.
- [ ] **Step 2: Recommendation.** `explain`: after a non-empty answer, `type="recommendation"`, actor `"edge-system"`, payload `{alert_id, question, answer, sources}`.
- [ ] **Step 3: Checklist step.** `checklist_step_done`: only when the `INSERT OR IGNORE` changed a row (`meta.changes`), actor = crew id, key `step:{alert_id}:{step}`.
- [ ] **Step 4: Playbook switch.** `put_playbook`: after the D1 batch, `type="playbook_switch"` with the new name, version and sha, then reset the cache first so the entry carries the new hash.
- [ ] **Step 5: Verify.** Run the simulator with `--anomaly tachycardia:okafor@5 --ticks 40 --step 60`; `GET /api/ledger` shows genesis, alert and autonomous_action entries; verify `ok`.

### Task 4: Cron verify and checkpoint

- [ ] **Step 1:** In `Default.scheduled`, after DONKI refresh, run the verify helper, print the result, then `ledger_log(type="checkpoint", summary=f"verify {'passed' if ok else 'failed'}: {reason or checked}", payload={"verify": result, "head": head})`.
- [ ] **Step 2:** Run dev with `--test-scheduled`; `curl "http://localhost:8787/__scheduled?cron=17+*/6+*+*+*"`; a checkpoint entry appears.

### Task 5: UI

**Files:**
- Create: `web/src/components/black-box.tsx` (latest entries, short hash = first 8 chars, arrow from each entry to its prev, Verify chain button with pass or fail text, tamper and restore when `demo`), `web/src/components/review-queue.tsx` (approve, override with optional note).
- Modify: `web/src/App.tsx` (third view `mission`, label "Mission control"), `web/src/components/my-health.tsx` (black-box panel filtered to the crew member plus edge entries).

- [ ] **Step 1:** Build components with existing `Button`, tokens and copy style.
- [ ] **Step 2:** `npm run build` in `web`, then in the browser: verify passes, tamper shows `hash mismatch at seq N`, restore passes again, approve removes the entry from the queue and adds a review entry.

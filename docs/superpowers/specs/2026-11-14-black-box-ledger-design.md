# Phase 8: black-box decision log (design)

Approved in conversation on 2026-11-14.

## Intent

A tamper-evident record of every decision the system and crew make (alerts, assistant answers,
checklist steps, edge actions, playbook switches, reviews), so mission control can review them
later and anyone can prove nothing was edited after the fact.

## Goals

- Hash-chained, append-only entries. One writer, so the chain cannot fork.
- Verify endpoint that names the exact bad seq ("hash mismatch at seq N").
- Review (approve or override) as new entries. Originals are never edited.
- Tamper and restore demo, only when `DEMO_MODE` is set.
- Cron verify plus a head checkpoint.
- Black-box panel in My Health and in a new Mission control tab with a review queue.

## Non-goals

- `data_share` entries. Privacy is not enforced anywhere yet (private readings reach the Earth
  view). The type exists in the schema, nothing writes it. TODO for the privacy phase.
- Backfilling the alerts that fired before phase 8. The chain starts at genesis.
- Auth0 identities. `actor` is `edge-system` or the crew id until phase 13.

## Anti-goals

- Any code path that rewrites or deletes an entry, outside the demo tamper/restore.
- A second writer (Workers or Astronaut DOs writing R2 ledger objects directly).

## Approaches

1. **Ledger DO as single writer, DO SQLite as source of truth, R2 and D1 as copies (picked).**
   The DO assigns seq and prev_hash and writes the entry to its own SQLite synchronously, so
   concurrent appends cannot interleave even though R2 and D1 calls await. An alarm retries any
   R2 or D1 copy that failed.
2. Ledger DO writes R2 first, then advances the head. Rejected: Durable Object input gates do not
   hold during R2 awaits, so two appends could read the same head and fork.
3. D1 as the chain store with a unique seq. Rejected: the spec wants R2 objects, and D1 alone
   gives no single writer.

## Decisions

- Entry fields: `seq, timestamp, type, entity_id, actor, summary, payload, playbook_name,
  playbook_hash, prev_hash, hash`. Canonical JSON: `json.dumps(sort_keys=True,
  separators=(",", ":"), ensure_ascii=False)`, UTF-8. `hash = sha256(canonical(entry - hash))`.
- Types: alert, recommendation, checklist_step, autonomous_action, data_share, review_approve,
  review_override, playbook_switch, genesis, plus `checkpoint` for the cron head record.
- `timestamp` is wall clock, ISO 8601 UTC. Mission time goes in `payload`.
- Genesis is seq 0, prev_hash 64 zeros, created lazily on the first append.
- R2 key `ledger/{seq:08d}.json`. D1 table `ledger (seq, hash, prev_hash, type, entity_id, timestamp)`.
- Hooks: alert fired (plus one autonomous_action listing its actions), assistant answer
  (recommendation), first time a checklist step is done, `PUT /api/playbook` (playbook_switch).
- Review queue: alert, recommendation and autonomous_action entries with no review entry yet.
  Review and demo endpoints are open, like the checklist routes, because the browser has no
  ingest key (shortcut until phase 13). Demo endpoints also need `DEMO_MODE`.
- Appends carry an idempotency `key` (e.g. `alert:{alert_id}`). A queue retry returns the
  existing entry instead of appending a duplicate. One review per seq.
- D1 index adds `summary` and `reviewed_seq` so the list and review queue need no R2 reads.
- Verify reads R2 in seq order, capped per request (subrequest limits), and reports `checked`.

## Left to the builder

UI layout details, page sizes, the verify cap value.

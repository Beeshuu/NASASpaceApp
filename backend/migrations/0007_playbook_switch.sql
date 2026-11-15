-- Playbook switcher: deprecated versions stay stored (ledger entries reference their hashes) but are hidden.
ALTER TABLE playbooks ADD COLUMN deprecated INTEGER NOT NULL DEFAULT 0;
-- v4 used twin.alpha and twin.beta, which the engine dropped in phase 6, so it no longer loads.
UPDATE playbooks SET deprecated = 1 WHERE name = 'crew-health' AND version = 4;

-- Which module each crew member is in, from their environment readings. alert_crew scope "group" uses it.
ALTER TABLE crew ADD COLUMN module TEXT;

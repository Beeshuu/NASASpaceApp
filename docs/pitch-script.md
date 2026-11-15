# Vital Orbit Pulse: pitch scripts

Read aloud. Text in [brackets] is a cue or a placeholder to fill in. Times assume a normal speaking pace.
Every claim below comes from the repo (README.md, docs/PROGRESS.md). Do not add numbers that are not in them.

---

## 1. Main pitch (about 3 minutes, 7 slides)

**Slide 1: cover (15 s)**
Hi, we are [team name]. This is Vital Orbit Pulse: crew health guidance for a Mars transit, for the moment when Earth is minutes away.

**Slide 2: problem (30 s)**
A signal between Earth and Mars takes between 3 and 22 minutes one way. Picture an astronaut with a heart-rate spike, a sleep crash, or a solar storm on the way. Ground control cannot answer in time. The crew needs guidance now. Earth still needs the full record, and it needs a record it can trust.

**Slide 3: answer (25 s)**
We built three things. First, the crew gets guidance at the edge, with no round trip. Second, Earth gets the same data only after the real light delay, so the demo respects the physics. Third, every decision goes into a black box that nobody can edit, including us.

**Slide 4: how it works (30 s)**
Sensor data goes through a Worker and a Queue into one Durable Object per astronaut. That object runs the playbook rules and pushes the result to the crew over a WebSocket right away. For Earth, the same object holds each message and sets an alarm for the real light delay. When the alarm fires, mission control gets it.

**Slide 5: demo (45 s)**
[Open vitalorbit.health, turn on demo mode.]
This is the crew view. [Trigger a solar event from NASA DONKI.] The playbook reacts at once and the crew gets a checklist. Now the mission control view: it shows a countdown, and the data lands only when the delay is over. The flight surgeon assistant explains readings from the playbook. It explains and does not diagnose. Crew also choose what the flight surgeon can see.

**Slide 6: trust (30 s)**
Each decision links to the one before it by hash. The records sit in R2 with Bucket Lock, so a write or delete is refused, even for us. [Show the tamper demo.] Here R2 refuses the edit, and when we change a demo copy, the hash check catches it. The Under the hood panel shows the live state of the system.

**Slide 7: close (15 s)**
The crew acts at once, and Earth gets a record it can verify. Thank you. We are at vitalorbit.health.

---

## 2. Cloudflare track (about 3 minutes; most important)

**Opening (20 s)**
Everything in Vital Orbit Pulse runs on Cloudflare, on one Python Worker. The problem has a hard rule: the crew must be guided at once, and Earth must see data only after the real light delay. Cloudflare products made each part of that rule a feature of the platform rather than code we had to invent.

**Product by product (about 2 minutes). Show the Under the hood panel while you speak.**

- **Workers (Python).** One Worker serves the API, the WebSockets and the frontend at the edge. The crew gets an answer with no trip to a central server.
- **Durable Objects.** One object per astronaut holds that person's state, runs the playbook engine and keeps the live WebSocket. A separate Ledger object is the only writer of the black box, so two writers can never fork the log. It assigns the sequence number and previous hash with no await in between.
- **Durable Object alarms.** This is the light delay. Each message goes into the object's outbox and `setAlarm` fires at the delay of the active playbook, and only then does it reach mission control. The browser only draws the countdown from the alarm time. It does not decide what Earth has.
- **R2 with Bucket Lock.** The ledger copy has an indefinite lock rule on the `ledger/` prefix. An overwrite or delete is refused with error 10069. In the tamper demo you see R2 refuse the edit. Then we edit a separate demo-only copy so the hash verification can show the catch.
- **Workflows (Python).** A critical alert starts `IncidentResponse`. It notifies the crew, then waits with `wait_for_event` for the shelter checklist to be finished, with a timeout. If the timeout hits, it pages the commander. Every step is written to the ledger. This survives restarts and waits for minutes, which a request handler cannot do.
- **Queues.** Ingest returns 202 at once. The consumer feeds each astronaut object in order, with retries, so a burst of sensor data does not overload the engine.
- **D1.** Latest readings, alerts, checklists, the ledger index and incidents.
- **Workers AI, AI Gateway and Vectorize.** The assistant's answers are grounded in the playbook guidance from Vectorize. Every model call goes through AI Gateway, and the Under the hood panel shows the last call and its latency.
- **Hyperdrive.** It connects our TypeScript Worker to Tiger Data (see the Tiger script).
- **Cron Triggers.** Every 6 hours: refresh NASA DONKI events and re-verify the ledger chain.
- **Cloudflare Access.** Login goes through Access with Auth0 in front. The Worker checks the Access token on every request and every socket.
- **Service bindings.** The Python Worker calls the TypeScript Tiger Worker over an RPC service binding. The Tiger Worker has no public URL.

**What we learned (20 s, honest)**
Python Workers have no TCP sockets, so a Postgres driver cannot connect. We tested it and `socket` is refused. That is why a small TypeScript Worker owns the database. We also note that Queues has no backlog API, so the panel shows our own count of messages sent minus messages acked.

**Close (15 s)**
Light delay, an edit-proof log, and an incident that outlives a restart: each one is a Cloudflare product used as intended. [Point to the Under the hood panel.] You can see all of it live.

**Likely questions**
- *Why Durable Objects and not a database row per astronaut?* The object holds the live socket, runs the playbook and sets the alarm in one place. A table row can do none of the three.
- *Can you really not delete a record?* Not in the locked prefix. R2 returns error 10069 on overwrite and delete. The demo-only copy exists so we can show the hash check without touching the real one.
- *What if Earth is unreachable?* The edge keeps guiding the crew. Delivery to Earth is an outbox plus an alarm, so it waits and is sent later.

---

## 3. Tiger Data sponsor (about 90 seconds)

Tiger Data is the long-term memory of the crew's health. Durable Objects and D1 hold the current state. Tiger Data holds months of history.

- `indicators` is a hypertable on `time`, with every reading: entity, domain, metric, value, unit and source. The queue consumer writes each batch in one insert. A unique key makes queue retries harmless. NASA DONKI events go to `donki_events`.
- The crew view shows trend charts per domain for 30, 90 or 180 days. They come from `time_bucket('1 day', time)` daily averages.
- Once per mission day, each astronaut object reads 90 days of daily averages. A new indicator starts from that baseline and does not learn from zero, and chronic domains get a weekly trend beside the fast slope in the twin forecast.
- It connects through Hyperdrive from a small TypeScript Worker, `vop-tiger`. A Python Worker cannot open a Postgres socket, which we tested.

**Likely question:** *Why a time-series database?* Readings arrive as a stream, and the product asks time questions: the daily average over 90 days, the weekly trend. `time_bucket` answers those directly.

---

## 4. Auth0 sponsor (about 60 seconds)

Two kinds of people use this app: the crew and mission control. They must see different things, and the sign-in has to prove who they are.

- Login runs through Auth0 behind Cloudflare Access. Auth0 only talks to Access, and never to the Worker.
- A post-login Auth0 action adds a role claim (`https://vitalorbit.health/role`) that Access copies into its token.
- The Worker checks that token on every request and every WebSocket, and it refuses an identity that has no role.
- Crew privacy builds on it: the flight surgeon sees only what the crew member shares.

**Likely question:** *Why not Auth0 directly on the Worker?* Access is already in front of the Worker, and it gives one check point for HTTP and sockets. Auth0 supplies the identity and the role.

---

## 5. NASA data (about 45 seconds; for any NASA judge)

Space weather is a real risk on a Mars transit, so we use real data. The Space Weather view is driven by NASA DONKI. The Worker refreshes DONKI events every 6 hours, and DONKI events can trigger playbook rules. Playbooks are swappable (a Mars transit playbook and an ISS low Earth orbit playbook), with different autonomy and delay.

We built this for the challenge "Create Health Monitoring Software for Astronauts on Space Missions."

---

## Before you present
- Fill `[team name]` and the challenge name.
- Rehearse the tamper demo and demo mode once on the real site. Have a backup screen recording.
- Do not state any number that is not in the README or PROGRESS.md.

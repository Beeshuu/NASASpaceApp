# Design direction: Vital Orbit Pulse

Status: approved by the project owner on 2026-11-15 and applied. Palette, fonts, motion level, and button plan were chosen by the owner; the rest was proposed by the designer and accepted. Replaces the navy + ice direction of 2026-11-14.

## Identity
A health instrument an astronaut reads alone, 20 minutes from Earth. The crew view is the primary view. Mission control is the second reader: an Earth flight surgeon reviewing what the edge already did.

## Feel
Void instrument. A near-black canvas, hairline frames, and a few large glowing-white readouts. Quiet until something changes. Dark only: the light mode and its toggle are removed.

Reference mood (mood only, nothing copied): hairline grid frames with corner ticks, small square markers before uppercase micro-labels, thin-line diagrams, dotted orbit rings, count-up numbers.

## Palette: graphite + void neutrals
No chromatic accent. White is the accent. Colour appears only when it means status.

| Token | Value | Use | Contrast on canvas |
|---|---|---|---|
| canvas | `#09090b` | page | - |
| panel | `#111114` | raised surfaces | - |
| hairline | `#26262b` | decorative frames, grid, dividers | decorative |
| control | `#71717a` | input and button borders, selected-tab underline | 4.1:1 |
| text | `#ededf0` | reading text, readouts | 16.8:1 |
| muted | `#a1a1aa` | labels, secondary text | 7.7:1 |
| accent | `#ffffff` | primary button fill, focus ring, live readout | 19.9:1 |

Status, never colour alone. Each has a shape, a word, and a colour:

| Status | Shape | Colour | Contrast |
|---|---|---|---|
| In range | ring | `#a1a1aa` (neutral, no green noise when all is well) | 7.7:1 |
| Watch | triangle | `#f2b84b` | 10.9:1 |
| Act now | filled square | `#ff8a7a` | 8.6:1 |

## Typography
- **Orbitron** (vibrant): the product name, page titles, and the big live readouts. Uppercase, wide tracking, 700. Never for sentences.
- **Space Mono** (low-key): micro-labels (11-12px uppercase, tracked), units, timestamps, table data, button text.
- **Sentences** (alert headline, checklist steps, explanations) are set in Space Mono too, owner's choice over Atkinson Hyperlegible. To keep them readable: 16px or larger, short lines, never uppercase.
- Scale, five steps only: 12 label / 16 body / 20 section / 32 readout / 48-64 hero readout and countdown.
- Digits use tabular figures so values do not jitter. Precision comes from the indicator: whole numbers for bpm, mmHg, min, ms.

## Spacing and layout
- 4px base. Three stack gaps only: 8 (within a group), 24 (between groups), 48 (between sections).
- One 12-column frame, max 1200px, with hairline rules and small corner ticks at section joins.
- Crew view order: status headline and open checklist, then readings grid, then trends, then check-in, assistant, and sharing (collapsed).
- Mission control order: review queue, then crew cards, then black box.
- Touch targets 44px or larger. Radius 2px. No shadows, no gradients, no cards inside cards.

## Components
- **Section header**: small square marker + Space Mono uppercase label, hairline above. One pattern everywhere.
- **Readout**: label on top, Orbitron value at 32px, unit in Space Mono, status shape + word beside it, delta on a second line.
- **Status headline**: status shape and word, then one plain sentence at 32px. Connection loss still outranks everything.
- **Tabs**: text + 2px white underline for the current view. One style for views and for crew.
- **Buttons**: one primary per screen (white fill, black text). Everything else is outline. 44px tall, Space Mono 14px uppercase. Destructive (Reset) is outline in the act colour, set apart, and asks for a second click.
- **Fields**: `control` border at 4.1:1, panel fill, visible label above.
- **Disclosure**: chevron + one summary line (sharing, assistant question, "how this works" text).

## Buttons: what changes
- Header: product name + three views + crew picker. Playbook select moves to mission control and demo, with a confirm. Light mode toggle deleted.
- Crew view: Verify chain, Demo: tamper, and Demo: restore removed. Ten share buttons become one collapsed panel with switches.
- Space weather: speed select becomes a three-way segment; Play sits beside the map.
- Mission control: tamper and restore removed. Override becomes one button that reveals its note field. Each ledger entry keeps its own row and its own approve call.
- Demo: one menu bar above the real app. Start, a date picker, "View as" (crew member, commander, flight surgeon; guests only), the playbook select for the commander, Reset set apart with a confirm. No speed buttons: a replay shortens the Earth delay to 20 s and says so. Tamper and restore live here only. `/guide` lists the dates.

## Voice
Calm and direct. Short plain sentences that state what changed and what to do. One line of explanation per panel; anything longer sits behind "How this works".

## Motion: calm plus
- Value changes: a changed number or status gets a short highlight (existing behaviour).
- Three signature moments: number ticker (readouts count up once when they first appear), beam (the Mars to Earth link, dashes travel only while a message is in transit), countdown (Earth delay).
- On screen load, once: readouts count up, chart lines draw in. 400-600ms, ease-out.
- Changing screen, role or crew member: the new screen replaces the old at once, then fades in and rises 8px, 180ms. The selected tab's underline and the "View as" fill slide to the new choice, 200ms. A new status headline or alert rises into place, 250ms.
- Transform and opacity only. With reduced motion, positions change at once.
- Space weather only: dotted orbit rings drift slowly. Apart from the beam while something is in transit, this is the only looping motion in the product.
- `prefers-reduced-motion`: no count-up, no line draw, no drift; values and final states appear at once. Replay keeps its one-step-per-second mode.

## Imagery
Two decorative images, WebP, lazy-loaded, `alt=""`, under 50 KB each. No people, logos, or real spacecraft.

- `public/starfield.webp`: faint star field and dust behind the space weather map.
- `public/limb.webp`: dark planet limb for the demo start state.

Both were generated with Higgsfield (Z Image, the model the free plan allows), then converted to greyscale WebP with ImageMagick. Prompts, to regenerate:

- Star field (1:1): "Hubble deep field style black and white photograph of deep space. Flat, uniformly jet-black background from edge to edge with no gradient, no glow, no horizon. Thousands of tiny sharp white stars of many different sizes and brightnesses densely and evenly scattered across the entire frame, plus soft faint grey dust clouds drifting diagonally. Monochrome, high detail, no colour, no planets, no lens flare, no diffraction spikes, no text, no logos, no spacecraft, no people."
- Planet limb (3:4): "Minimal monochrome hero image: the curved limb of a dark rocky planet seen from orbit, filling the lower right, lit by a thin crescent of cold white light along its edge, against a near-black (#09090b) void with a few faint tiny stars. Graphite greys and white only, fine film grain, soft falloff into black on the left and top so text can sit there. No text, no logos, no spacecraft, no satellites, no people, no lens flare."

## Rules that do not bend
Status never by colour alone. Text contrast 4.5:1 or better; control boundaries 3:1 or better. Targets 44px. Reduced motion respected. No change to data, WebSocket, Mars mode, or ledger behaviour.

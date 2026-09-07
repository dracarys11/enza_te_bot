# Python Click Migration Memory

Long-term click-region memory for migrating verified UI controls from
ZCode Browser/Computer-Use operation to a local Python executor.

Governance: `enza_memory/MEMORY_PROTOCOL.md` + `../MEMORY_SCHEMA.md` honesty
rules apply. Artifacts here are CANDIDATE evidence, not executable policy.

## Files

- `viewport_profiles.json` — game-viewport geometry profiles; normalized
  coordinate contract. Active: `MAC_CURRENT_V1` (1280x720, left/top=0
  assumption unverified).
- `control_regions.json` — one entry per `ROOM:CONTROL` with normalized boxes,
  preconditions, postconditions, sample counts, promotion stage.
- `click_samples.jsonl` — append-only per-click evidence. A sample without
  fresh post-action verification must not be `SUCCESS`.
- `transient_timing.jsonl` — safe transient skip regions + timing learning
  (`OBSERVE -> PROBE -> REPLICATE -> FAST_PATH_READY`). Never mixed with
  semantic control memory.
- `migration_status.json` — aggregated stage rollup and blockers.

## Coordinate contract

All durable coordinates are normalized to the game viewport:
`nx = (x - left) / width`, `ny = (y - top) / height`. Raw screen/viewport
coordinates go in `*_debug` / `raw` fields as run-local provenance only.

## Live-run append contract (silent, no disruption)

On every live run, when a control with an identifiable visual box is clicked
as part of the normal business action:

1. Before click: capture `visual_box_norm` + frame/screenshot reference,
   room/state, interactability (value and enabled are separate fields).
2. Click one valid point (record `click_point_norm` + raw debug).
3. Fresh observe; classify `SUCCESS | NO_EFFECT | WRONG_TARGET | UNKNOWN`.
4. Append one line to `click_samples.jsonl`; update counters, stage, and
   `migration_status.json`.

Never record as SUCCESS: blind clicks, unknown identity, unknown
postcondition, transition pushed by another action, ambiguous batch clicks,
disabled/animation-phase no-effects, unverifiable operator manual clicks
(manual evidence goes in a separate `MANUAL_SUCCESS_EVIDENCE` note).
No edge-probing clicks, no destructive exploration — natural samples only.

## Promotion stages

`OBSERVED -> CLICK_VALIDATED -> REPLICATED -> PYTHON_READY`
A single success never promotes. `PYTHON_READY` requires a stable proven
region, explicit preconditions, and a verifiable postcondition.

## Reporting to operator (only these)

New control reaches REPLICATED; control reaches PYTHON_READY; visual box and
clickable region visibly disagree; dangerous overlap found.

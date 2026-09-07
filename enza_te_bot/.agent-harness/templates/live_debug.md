# Live-debug authorization

## Approved command

`<exact command>`

## Risk level

`LEVEL_0_OBSERVE_ONLY | LEVEL_1_BOUNDED_SAFE_UI | LEVEL_2_BUSINESS_ACTION | LEVEL_3_COST_OR_IRREVERSIBLE`

## Allowed click scope

`NONE` or describe the already-bounded capability/region.

## Terminal condition

Describe the state/effect that ends this transaction successfully.

## Protected states

- `<state or condition>`

## Attempt bound

Maximum live-debug attempts: `3`

## Irreversible effects

`NONE` or list each explicitly authorized effect.

## Attempt record

- Attempt:
- Outcome classification:
- Last state:
- Stdout summary:
- Trace/evidence paths:
- Minimal repair:
- Focused validation:
- Retry permitted: `YES | NO`

## Final disposition

`SUCCESS | STOPPED | EXCEPTION_REPORT`


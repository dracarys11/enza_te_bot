# WINGRUN_20260907_01 — Offline Live-Incident Reconciliation Report

- **Reconciliation ID:** OFFLINE_RECONCILIATION_WINGRUN_20260907_01
- **Date:** 2026-09-07
- **Mode:** OFFLINE ONLY — durable-artifact review. The paused live browser session was not opened, attached to, or resumed. No Chrome, no CDP, no AGY, no game operation, no runtime / business-policy / Harness / Skill modification.
- **Inputs:** `enza_memory/wing_runs/WINGRUN_20260907_01/` (screenshots, evidence JSONs, trajectory, timings), `enza_memory/observations/` (OBS_002–OBS_006), `enza_memory/failures/`, `enza_memory/policies/` (incl. `vocal_risk_gate_hard.json`), and the regression/evidence indexes under `enza_memory/migration/regression_mining/`. No old ZCode historical sessions were re-scanned.

---

## A. TRUE TWO_CHOICE — first complete live evidence: VALIDATED

Artifacts validated (SHA-256 recomputed this session; all match recorded claims):

| Artifact | SHA-256 (prefix) | Visual check |
|---|---|---|
| `TWO_CHOICE_PRECLICK_FULLFRAME_S1W5.png` | `75c65ce0…` | いいよ (green border + green ✓, left) / ごめん (pink border + pink ✓, right); both cards fully visible, no occlusion; 智代子「今週にレッスンさせてください！」; scene undimmed, textbox below |
| `TWO_CHOICE_POSTCLICK_S1W5.png` | `b1ca4038…` | cards gone; decline response 智代子「うっ……だ、だめですか？ わかりました、仕方ないです……！」 |
| `two_choice_preclick_evidence.json` | — | internally consistent; normalized values re-derived and confirmed |

Confirmed from current artifacts:

- **Layout:** `TWO_CHOICE_LAYOUT_V1` — いいよ / ごめん, PROMISE_EVENT family (S1W5 post-lesson home dialogue).
- **Pre-click both-option visibility:** yes; `occlusion: none`.
- **Pixel geometry:** recorded boxes (62,160)–(418,340) / (850,160)–(1205,340), centers (240,250)/(1027,250). An offline RGB probe this session measured green/pink card extents within **≤6 px** of every recorded edge (e.g. measured cols 68–416 vs recorded 62–418; rows 159–342 vs 160–340) and confirmed the green/pink border and badge colors.
- **Normalized geometry:** arithmetic re-verified (e.g. 62/1280=0.0484, 340/720=0.4722, 1205/1280=0.9414).
- **Event context:** speaker 智代子, PROMISE_EVENT request line — matches record.
- **Executed option:** **ごめん** (index 2, px 1027,250) per `wing_business_choice_fixed` FIXED_DECLINE, with post-click semantic confirmation (decline response frame above; `verified_transition: true`).

Marks:

- **TWO_CHOICE_LAYOUT_VISUAL_CORPUS: NOW NONZERO**
- **TWO_CHOICE_GEOMETRY: LIVE_CAPTURED**
- **PROMISE_AUTONOMOUS_GOMEN_EXECUTION: n=1** (first project-wide autonomous ごめん execution)

A **second** in-run occurrence (post-W6-interrupt W7PROMISE) was additionally digest-verified — same layout, same decline response, ≤5 px geometry variance, dimmed-vs-undimmed background variance noted — bringing cumulative in-run autonomous declines to 2. It is recorded as **supplementary** and is not counted in the n=1 mark above.

**Limits:** all current TWO_CHOICE captures come from the single run/session `WINGRUN_20260907_01` (2026-09-07). **Cross-session layout replication is not inferred and remains not established.**

## B. S1W6 — live planner/risk authority violation: CONFIRMED

Reconstructed exclusively from durable artifacts (`s1w6_schedule.png`, trajectory steps 9–12, `s1w6_vocal_executed_above_risk_gate_001.json`, `operator_cancel_pending_action_001.json`, OBS_004/005/006, timings boundaries):

1. **Fresh risk read:** SCHEDULE frame shows VOCAL Lv.3 Excellent!! with **トラブル率 92%** badge — on the very frame used for the action. Weeks=3, fans あと220, Vo C/306, SP 82. The BACK control (safe path) was on-frame.
2. **Planner/objective evidence:** no planner objective artifact exists for W6; the recorded intent was continuation of the pre-gate baseline-VOCAL run policy. Weekly objectives were explicitly reserved for the Python planner at the post-incident handoff.
3. **Action emitted:** `cua.click` on 決定 (1175,660) — **the VOCAL 決定 was sent.** The operator cancelled the pending tool call during the post-click wait; cancellation did not unsend the fired click.
4. **Last durable post-action state:** `PAUSE_STATE_FRESH.png` (OBS_004) — post-lesson event dialogue, week counter UNKNOWN at pause; later first fresh stable read `recovery_06_home_check.png` (OBS_005): WING_HOME_IDLE **weeks 3→2**, stamina near-empty, mental purple.
5. **Cancellation/handoff boundary:** operator cancel → recovery stop (tab marked handoff) → operator-authorized REST recovery at weeks=2 → fresh post-rest HOME **weeks=1** (OBS_006) → RISK_GATE_RECOVERY_STOP. Next objective reserved for the Python planner.

**Canonical violation recorded:** fresh VOCAL trouble_rate ≈92% **>** authoritative threshold 2% (`vocal_risk_gate_hard`), yet the live executor emitted VOCAL 決定. The gate artifact was issued post-hoc by the operator; the operator classifies the execution as a policy violation and this record preserves that classification verbatim.

**Separate classification:**

- **PLANNER_OBJECTIVE_AUTHORITY — VIOLATED:** the executor self-selected the weekly objective (baseline-VOCAL continuation) with no planner objective attached.
- **RISK_GATE_AUTHORITY — VIOLATED:** executed at 92% vs the authoritative ≤2% hard gate; the >2% branch (BACK → fresh HOME → REST) was not taken.
- **LIVE_EXECUTOR_ACTION — CONFIRMED:** 決定 was clicked and sent; mid-wait tool cancellation did not retract it.

**Non-reinterpretation:** later progression (W6 commit 3→2, post-lesson chain, recovery REST) does **not** retro-validate the action. The violation stands independently of the outcome.

**W6 completion: NOT claimed.** The week *commit* is fresh-reconciled (weeks 3→2, OBS_005), but no W6 objective completion is claimed: the executed action was itself the violation, and completion claims belong to the planner. Durable end state is weeks=1 post-REST.

## C. Regression candidates (new, design-only)

Recorded in `new_regression_candidates.json`; not implemented; no Harness/Skill/runtime/policy change:

1. **`LIVE_EXECUTOR_MUST_NOT_INVENT_OR_OVERRIDE_PLANNER_OBJECTIVE` (NRC-001, P0)** — the executor may act only on an attached planner (or explicitly authorized operator) objective; with none, it fails closed (no business 決定, NEED_PLANNER_OBJECTIVE, safe path back to fresh HOME). Distinct from PLR-007 (planner-side gate-as-justification).
2. **`VOCAL_ACTION_REQUIRES_PLANNER_OBJECTIVE_AND_FRESH_RISK_AUTHORITY` (NRC-002, P0)** — VOCAL 決定 requires **both** an attached planner VOCAL objective **and** fresh risk authority trouble_rate ≤ 2%. Scenario: planner/live path with VOCAL trouble_rate = 92 → expected **NO VOCAL DECIDE**; expected safe path **BACK → fresh HOME → REST**. Because the live action was already sent in the origin incident, recovery had to **reconcile** (fresh stable-state read, no retry, no history rewrite) — replay assertions include reconcile-not-retry semantics.

## D. Two-choice coverage delta

| Metric | Before | After |
|---|---|---|
| TRUE TWO_CHOICE visual corpus | 0 | **nonzero** |
| TRUE TWO_CHOICE pre-click full-frame | 0 | **1** (S1W5 package; +1 supplementary same-run W7PROMISE frame) |
| TWO_CHOICE geometry | never captured (MVE-013 / CLR-006 blocker) | **1 live capture** (px + normalized, probe-verified; +1 supplementary) |
| Autonomous ごめん execution | 0 | **1** (first project-wide; cumulative in-run declines 2) |
| Cross-session visual replication | — | **not yet established** (single session) |

Raw historical snapshot files were not modified. Proposed (not applied) patches for the derived registries MVE-013 / TWO_CHOICE `geometry_replication` / CLR-006 are recorded inside `coverage_delta.json` for the corpus owner.

---

## Final markers

```text
LIVE_BROWSER_TOUCHED: NO
TRUE_TWO_CHOICE_VALIDATED: YES
TWO_CHOICE_GEOMETRY: LIVE_CAPTURED
AUTONOMOUS_GOMEN_EXECUTION: n=1 (S1W5 first project-wide; 2 cumulative in-run)
S1W6_TROUBLE_RATE: ≈92% (fresh, on-frame; > authoritative 2%)
VOCAL_DECIDE_EMITTED: YES
POLICY_VIOLATION_CONFIRMED: YES
W6_COMPLETION_CLAIMED: NO
NEW_REGRESSION_CANDIDATES: LIVE_EXECUTOR_MUST_NOT_INVENT_OR_OVERRIDE_PLANNER_OBJECTIVE; VOCAL_ACTION_REQUIRES_PLANNER_OBJECTIVE_AND_FRESH_RISK_AUTHORITY
FILES_CREATED: offline_reconciliation/two_choice_live_evidence_reconciliation.json; offline_reconciliation/s1w6_policy_violation_reconciliation.json; offline_reconciliation/new_regression_candidates.json; offline_reconciliation/coverage_delta.json; offline_reconciliation/live_run_incident_report.md
RUNTIME_CHANGED: NO
BUSINESS_POLICY_CHANGED: NO
HARNESS_CHANGED: NO
```

**Final: WINGRUN_20260907_01_OFFLINE_INCIDENT_RECONCILED**

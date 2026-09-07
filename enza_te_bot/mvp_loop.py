"""MVP closed-loop controller for the minimal WING prep segment.

Scope (nothing else):
    HOME -> WING_SELECTION -> TRAINING_SETTINGS -> VOCAL +1

Components:
- classify():  VisionObservation -> CurrentStateCandidate
               (HOME / WING_SELECTION / TRAINING_SETTINGS only)
- resolve():   TargetResolver for VOCAL_PLUS only -> ActionRequestCandidate
               (no click, no coordinates, no execution permission)
- verify():    post-action counter verification — same counter location,
               old value -> new value, expecting 0/20 -> 1/20

Reuses the VisionObservation contract and the ObservationInterpreter's
evidence rules. Does NOT touch the legacy runner, ActionBoundary runtime,
or any memory system. No live automation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from vision_observation_schema import VisionObservation

SUPPORTED_STATES = frozenset({"HOME", "WING_SELECTION", "TRAINING_SETTINGS"})

# State required before a VOCAL_PLUS request may even be produced.
VOCAL_PLUS_REQUIRED_STATE = "TRAINING_SETTINGS"


@dataclass(frozen=True)
class CurrentStateCandidate:
    state: str  # one of SUPPORTED_STATES or "UNKNOWN"
    evidence_refs: tuple[str, ...]
    confidence: float
    unknowns: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "evidence_refs": list(self.evidence_refs),
            "confidence": self.confidence,
            "unknowns": list(self.unknowns),
        }


@dataclass(frozen=True)
class ActionRequestCandidate:
    """Resolved-but-not-executable action proposal (no click, no permission)."""

    action_type: str  # "VOCAL_PLUS" only in this MVP
    target_element_id: str
    source_observation_id: str
    evidence_refs: tuple[str, ...]
    expected_verification: dict[str, Any]
    uncertainty_status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "target_element_id": self.target_element_id,
            "source_observation_id": self.source_observation_id,
            "evidence_refs": list(self.evidence_refs),
            "expected_verification": self.expected_verification,
            "uncertainty_status": self.uncertainty_status,
        }


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    counter_id: str | None
    old_value: int | float | None
    new_value: int | float | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "counter_id": self.counter_id,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "reason": self.reason,
        }


def _bbox_of(region: dict[str, Any]) -> tuple[float, float, float, float] | None:
    raw = region.get("bbox")
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        return (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
    return None


def _same_location(a: tuple[float, float, float, float], b: tuple[float, float, float, float],
                   tolerance: float = 8.0) -> bool:
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


def classify(vision_payload: dict[str, Any], *,
             roundtrip_verified_labels: Iterable[str] = ()) -> CurrentStateCandidate:
    """Produce a single CurrentStateCandidate from a VisionObservation.

    Evidence rules (inherited from ObservationInterpreter v0.1):
    - title_text_read / roundtrip_verified may establish identity
    - coordinate_only / shape_only never may; missing title -> UNKNOWN
    - ambiguity between two supported labels -> UNKNOWN (never a guess)
    """
    obs = VisionObservation.from_payload(vision_payload)  # contract-enforced

    candidates: list[tuple[str, tuple[str, ...], str, float]] = []
    for region in obs.text_regions:
        text = region.get("text")
        conf = region.get("confidence")
        if text == "ホーム" and isinstance(conf, (int, float)) and conf >= 0.9:
            candidates.append(("HOME", (f"text_region:{region.get('id')} ('ホーム', conf {conf})"),
                               "title_text_read", float(conf)))
        elif text == "研修設定" and isinstance(conf, (int, float)) and conf >= 0.9:
            candidates.append(("TRAINING_SETTINGS", (f"text_region:{region.get('id')} ('研修設定', conf {conf})"),
                               "title_text_read", float(conf)))
        elif text == "W.I.N.G." and isinstance(conf, (int, float)) and conf >= 0.9:
            candidates.append(("WING_SELECTION", (f"text_region:{region.get('id')} ('W.I.N.G.', conf {conf})"),
                               "title_text_read", float(conf)))
    for label in roundtrip_verified_labels:
        if label in SUPPORTED_STATES and not any(c[0] == label for c in candidates):
            candidates.append((label, ("caller_memory:roundtrip_verified",),
                               "roundtrip_verified", 0.8))

    labels = {c[0] for c in candidates}
    if len(labels) == 1:
        state, refs, _source, conf = candidates[0]
        return CurrentStateCandidate(state, refs, conf, unknowns=())
    if len(labels) > 1:
        return CurrentStateCandidate(
            "UNKNOWN", (),
            0.3,
            unknowns=(f"ambiguous title evidence: multiple supported labels {sorted(labels)}",),
        )
    return CurrentStateCandidate(
        "UNKNOWN", (),
        0.0,
        unknowns=("no title-text evidence for any supported state; "
                  "coordinate/shape evidence is not admissible for identity",),
    )


def resolve(vision_payload: dict[str, Any], state: CurrentStateCandidate) -> ActionRequestCandidate | None:
    """TargetResolver: VOCAL_PLUS only. Returns None on any doubt.

    Preconditions: state is TRAINING_SETTINGS; a ボーカル label, a numeric
    counter with value 0 < max in the same column, and a circle_button in the
    same column band exist. Right-of-counter is ASSUMED to be the increment
    control; the assumption is carried explicitly, never hidden.
    """
    if state.state != VOCAL_PLUS_REQUIRED_STATE:
        return None
    obs = VisionObservation.from_payload(vision_payload)

    for label in [r for r in obs.text_regions if r.get("text") == "ボーカル"]:
        lx, ly, lw, lh = label["bbox"]
        column_x = lx + lw / 2
        for numeric in obs.numeric_regions:
            bbox = _bbox_of(numeric)
            if bbox is None:
                continue
            nx, ny, nw, nh = bbox
            if abs((nx + nw / 2) - column_x) >= 120 or ny <= ly:
                continue
            value, max_value = numeric.get("value"), numeric.get("max_value")
            if not (isinstance(value, (int, float)) and isinstance(max_value, (int, float))):
                continue
            buttons = [
                e for e in obs.interaction_candidates
                if isinstance(e.get("bbox"), (list, tuple))
                and abs((e["bbox"][0] + e["bbox"][2] / 2) - column_x) < 120
                and abs((e["bbox"][1] + e["bbox"][3] / 2) - ny) < 60
                and e.get("appearance", {}).get("shape") == "circle_button"
            ]
            if not buttons:
                continue
            target = max(buttons, key=lambda e: e["bbox"][0])  # column-right (ASSUMED +)
            return ActionRequestCandidate(
                action_type="VOCAL_PLUS",
                target_element_id=str(target.get("id")),
                source_observation_id=obs.observation_id,
                evidence_refs=(
                    f"source_observation:{obs.observation_id}",
                    f"state:{state.state} ({state.evidence_refs[0] if state.evidence_refs else 'n/a'})",
                    f"text_region:{label.get('id')} ('ボーカル')",
                    f"numeric_region:{numeric.get('id')} (value {value}/{max_value})",
                    f"interaction_candidate:{target.get('id')} (circle_button, column-right)",
                ),
                expected_verification={
                    "counter_region_id": numeric.get("id"),
                    "same_location_required": True,
                    "old_value": value,
                    "new_value": value + 1,
                    "note": f"expected {value}/{max_value} -> {value + 1}/{max_value}",
                },
                uncertainty_status=(
                    "ASSUMED: column-right circle button is the increment control; "
                    "verify by counter delta at the same bbox after action"
                ),
            )
    return None


def verify(before_payload: dict[str, Any], after_payload: dict[str, Any],
           expected_counter_id: str | None = None) -> VerificationResult:
    """Post-action verification: same counter location, old->new value delta +1.

    Requires the counter to be found at the SAME bbox in both observations
    (location match, tolerance 8px) with new == old + 1. Anything else fails.
    """
    before = VisionObservation.from_payload(before_payload)
    after = VisionObservation.from_payload(after_payload)

    def find(obs: VisionObservation) -> dict[str, Any] | None:
        if expected_counter_id is not None:
            for region in obs.numeric_regions:
                if region.get("id") == expected_counter_id:
                    return region
            return None
        return obs.numeric_regions[0] if len(obs.numeric_regions) == 1 else None

    b, a = find(before), find(after)
    if b is None or a is None:
        return VerificationResult(False, None, None, None,
                                  "counter region not uniquely identifiable in before/after")
    bb, ab = _bbox_of(b), _bbox_of(a)
    if bb is None or ab is None or not _same_location(bb, ab):
        return VerificationResult(False, str(a.get("id")), b.get("value"), a.get("value"),
                                  "counter location changed between observations — not the same counter")
    old, new = b.get("value"), a.get("value")
    if not (isinstance(old, (int, float)) and isinstance(new, (int, float))):
        return VerificationResult(False, str(a.get("id")), old, new, "counter values not numeric")
    if new != old + 1:
        return VerificationResult(False, str(a.get("id")), old, new,
                                  f"counter delta != +1 (got {old} -> {new})")
    return VerificationResult(True, str(a.get("id")), old, new,
                              f"verified: same location, {old} -> {new}")

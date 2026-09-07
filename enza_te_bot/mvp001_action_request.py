"""MVP-001 ActionRequest Adapter.

Consumes an ObservationInterpretation (see observation_interpreter.py) plus
the VisionObservation payload it was derived from, and produces ActionRequest
objects for the minimal grounded loop:

    HOME --PRODUCE_OPEN--> WING_SELECTION --OPEN_TRAINING_SETTINGS-->
    TRAINING_SETTINGS --INCREASE_VOCAL--> (vocal counter +1)

Supported intents and their required state/evidence:
- PRODUCE_OPEN:            HOME established via roundtrip_verified
- OPEN_TRAINING_SETTINGS:  WING_SELECTION established via 'W.I.N.G.' title text
- INCREASE_VOCAL:          TRAINING_SETTINGS established via '研修設定' title
                           text + a ボーカル counter

Every request carries source_observation_id, intent, target_element_id,
evidence_refs, uncertainty_status. The adapter REJECTS:
- UNKNOWN state (no admissible semantic candidate)
- coordinate-only state identity
- screenshot-only targets (an element with no linked-text/counter evidence)
- missing evidence fields

No execution. No permission generation. ActionRequest is inert data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vision_observation_schema import VisionObservation


@dataclass(frozen=True)
class ActionRequest:
    """Inert action proposal — deliberately has NO execute() and NO permission."""

    request_id: str
    source_observation_id: str
    intent: str
    target_element_id: str
    evidence_refs: tuple[str, ...]
    uncertainty_status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "source_observation_id": self.source_observation_id,
            "intent": self.intent,
            "target_element_id": self.target_element_id,
            "evidence_refs": list(self.evidence_refs),
            "uncertainty_status": self.uncertainty_status,
        }


class AdapterRejection(ValueError):
    """Raised when the loop's grounding rules refuse to produce a request."""


def _labels(interpretation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["label"]: c for c in interpretation.get("semantic_candidates", [])}


def _state_for(interpretation: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """Admissible state per the intent table; UNKNOWN/coordinate-only rejected."""
    candidates = interpretation.get("semantic_candidates", [])
    if not candidates:
        raise AdapterRejection("state UNKNOWN: no semantic candidates — refusing request")
    labels = _labels(interpretation)
    # Roundtrip + title evidence may coexist for one label; ambiguity across
    # labels is treated as UNKNOWN (inherited from the interpreter contract).
    if len(labels) > 1:
        raise AdapterRejection(f"state ambiguous across labels {sorted(labels)} — refusing request")
    label, candidate = next(iter(labels.items()))
    if candidate.get("identity_source") in ("coordinate_only", "shape_only"):
        raise AdapterRejection("coordinate-only identity is not admissible for any intent")
    return label, candidate


def _element_linked_to_text(obs: VisionObservation, text: str) -> dict[str, Any] | None:
    text_ids = {r.get("id") for r in obs.text_regions if r.get("text") == text}
    for element in obs.interaction_candidates:
        if set(element.get("linked_text_ids", [])) & text_ids:
            return element
    return None


def build_action_request(interpretation: dict[str, Any],
                         vision_payload: dict[str, Any]) -> ActionRequest:
    """Build the single next ActionRequest for the loop, or raise AdapterRejection.

    The interpretation supplies admissible state identity; the vision payload
    supplies element grounding (ids only — never coordinates).
    """
    if interpretation.get("observation_id") != vision_payload.get("observation_id"):
        raise AdapterRejection("interpretation/vision observation_id mismatch")
    obs = VisionObservation.from_payload(vision_payload)
    state, state_candidate = _state_for(interpretation)

    if state == "HOME":
        # Requires roundtrip-verified HOME (per intent table) + a labeled
        # produce button. A screenshot-only button is rejected.
        if state_candidate.get("identity_source") != "roundtrip_verified":
            raise AdapterRejection("PRODUCE_OPEN requires HOME established via roundtrip_verified")
        element = _element_linked_to_text(obs, "プロデュース")
        if element is None:
            raise AdapterRejection(
                "no interaction candidate linked to text 'プロデュース' — screenshot-only target rejected"
            )
        return ActionRequest(
            request_id=f"REQ-{obs.observation_id}-PRODUCE_OPEN",
            source_observation_id=obs.observation_id,
            intent="PRODUCE_OPEN",
            target_element_id=str(element.get("id")),
            evidence_refs=(
                f"state:HOME via {state_candidate.get('identity_source')}",
                f"text_region:('プロデュース') label",
                f"interaction_candidate:{element.get('id')} linked to that label",
            ),
            uncertainty_status="STABLE: roundtrip-verified state + label-linked button",
        )

    if state == "WING_SELECTION":
        if state_candidate.get("identity_source") != "title_text_read":
            raise AdapterRejection("OPEN_TRAINING_SETTINGS requires WING_SELECTION via title text")
        element = _element_linked_to_text(obs, "研修設定")
        if element is None:
            raise AdapterRejection(
                "no interaction candidate linked to text '研修設定' — screenshot-only target rejected"
            )
        return ActionRequest(
            request_id=f"REQ-{obs.observation_id}-OPEN_TRAINING_SETTINGS",
            source_observation_id=obs.observation_id,
            intent="OPEN_TRAINING_SETTINGS",
            target_element_id=str(element.get("id")),
            evidence_refs=(
                "state:WING_SELECTION via title_text_read ('W.I.N.G.')",
                "text_region:('研修設定') label",
                f"interaction_candidate:{element.get('id')} linked to that label",
            ),
            uncertainty_status="STABLE: title-read state + label-linked button",
        )

    if state == "TRAINING_SETTINGS":
        if state_candidate.get("identity_source") != "title_text_read":
            raise AdapterRejection("INCREASE_VOCAL requires TRAINING_SETTINGS via title text")
        # ボーカル label + same-column counter below max + column-right circle.
        for label in [r for r in obs.text_regions if r.get("text") == "ボーカル"]:
            column_x = label["bbox"][0] + label["bbox"][2] / 2
            for numeric in obs.numeric_regions:
                nx, ny, nw, nh = numeric["bbox"]
                if abs((nx + nw / 2) - column_x) >= 120 or ny <= label["bbox"][1]:
                    continue
                value, max_value = numeric.get("value"), numeric.get("max_value")
                if not (isinstance(value, (int, float)) and value < max_value):
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
                target = max(buttons, key=lambda e: e["bbox"][0])
                return ActionRequest(
                    request_id=f"REQ-{obs.observation_id}-INCREASE_VOCAL",
                    source_observation_id=obs.observation_id,
                    intent="INCREASE_VOCAL",
                    target_element_id=str(target.get("id")),
                    evidence_refs=(
                        "state:TRAINING_SETTINGS via title_text_read ('研修設定')",
                        f"text_region:{label.get('id')} ('ボーカル')",
                        f"numeric_region:{numeric.get('id')} (value {value}/{max_value})",
                        f"interaction_candidate:{target.get('id')} (circle_button, column-right)",
                    ),
                    uncertainty_status=(
                        "ASSUMED: column-right circle is the increment control; "
                        "verify by same-location counter delta after action"
                    ),
                )
        raise AdapterRejection("no admissible ボーカル counter + button pair — missing evidence")

    raise AdapterRejection(f"state '{state}' has no supported intent in MVP-001")

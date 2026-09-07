"""HOME identity grounding — JSON-only gate before business consumption.

Contract home_identity@1: decides HOME_CONFIRMED / HOME_AMBIGUOUS / NOT_HOME
from a fused VisionObservation, GroundedElements, and a human-authored
HOME_IDENTITY_SPEC. Never reads pixels; never parses a screenshot.

Decision axioms (asymmetric-conservative):
- HOME_CONFIRMED requires every required positive anchor confirmed, zero
  contradicting negative evidence, and zero overlay contamination on
  required anchors.
- NOT_HOME requires affirmative negative evidence, never mere absence.
- Everything else -- sensor blindness, partial evidence, contaminated
  required anchors, unknown spec entries -- is HOME_AMBIGUOUS with reasons.

Overlay contamination (P0-2): an overlay bbox intersecting an anchor's
effective region disqualifies that matching region from confirming
anything; contaminated required anchors force at most HOME_AMBIGUOUS.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from exploration.home_projection import project_home_fields


CONTRACT = "home_identity@1"

HOME_CONFIRMED = "HOME_CONFIRMED"
HOME_AMBIGUOUS = "HOME_AMBIGUOUS"
NOT_HOME = "NOT_HOME"

_ANCHOR_KINDS = {"field_value", "text", "element", "element_density"}


def _boxes_intersect(a: Iterable[float], b: Iterable[float]) -> bool:
    ax, ay, aw, ah = (float(v) for v in a)
    bx, by, bw, bh = (float(v) for v in b)
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _anchor_region(anchor: Mapping[str, Any], viewport: Mapping[str, int]) -> tuple[float, float, float, float] | None:
    roi = anchor.get("roi")
    if not (isinstance(roi, (list, tuple)) and len(roi) == 4):
        return None
    left, top, right, bottom = (float(v) for v in roi)
    width = float(viewport.get("width", 0))
    height = float(viewport.get("height", 0))
    return (left * width, top * height,
            (right - left) * width, (bottom - top) * height)


def _overlays(observation: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [o for o in observation.get("overlay_regions", []) or []
            if isinstance(o, Mapping) and o.get("bbox")]


def _contaminated_by(bbox: Iterable[float],
                     overlays: list[dict[str, Any]]) -> list[str]:
    return [str(o.get("id", "")) for o in overlays
            if _boxes_intersect(bbox, o["bbox"])]


def _evaluate_field_value(anchor: Mapping[str, Any], observation: Mapping[str, Any],
                          grounded: list[Mapping[str, Any]], viewport: Mapping[str, int],
                          overlays: list[dict[str, Any]],
                          min_confidence: float,
                          field_projection: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """field_value anchors reuse the projection's per-field evidence.

    The driver's projection (with clarification provenance) is preferred;
    otherwise the anchor's own ROI re-projects from the observation.
    """
    name = str(anchor.get("field", ""))
    field = None
    if field_projection is not None:
        field = (field_projection.get("fields") or {}).get(name)
    if field is None:
        projection = project_home_fields(observation, grounded, {
            name: {"roi": anchor["roi"],
                   **({"range": anchor["range"]} if "range" in anchor else {})}
        } if anchor.get("roi") else None)
        field = projection["fields"].get(name) if name else None
    if field is None:
        return {"matched": False, "evidence_ids": [], "note": "field anchor missing field/roi"}

    # Provenance circularity guard: a human_clarification answer may complete
    # the BUSINESS value of a field, but it can never open the identity gate.
    # Only observation-derived (vision_fusion) evidence counts here.
    source = str(field.get("source", ""))
    human_only = source == "human_clarification"
    known = field["status"] == "KNOWN"
    confirmed = known and not human_only
    evidence_ids = list(field.get("evidence_ids", []))
    contaminated: list[str] = []
    if confirmed:
        observation_regions = {
            str(r.get("id")): r for r in observation.get("text_regions", []) or []
            if isinstance(r, Mapping) and r.get("id")}
        for evidence_id in evidence_ids:
            region = observation_regions.get(evidence_id)
            if region and region.get("bbox"):
                contaminated.extend(_contaminated_by(region["bbox"], overlays))
    confirmed = confirmed and not contaminated
    return {
        "matched": confirmed,
        "evidence_ids": evidence_ids,
        "overlay_contaminated": bool(contaminated),
        "overlay_ids": contaminated,
        "field_status": field["status"],
        "field_source": source or None,
        "human_provenance": human_only,
        "note": ("identity_evidence_not_visual (human_clarification)"
                 if human_only and known else
                 "" if confirmed else
                 f"field_status={field['status']}"
                 + (f" overlay={contaminated}" if contaminated else "")),
    }


def _evaluate_text(anchor: Mapping[str, Any], observation: Mapping[str, Any],
                   overlays: list[dict[str, Any]],
                   min_confidence: float) -> dict[str, Any]:
    match = anchor.get("match") or {}
    expected = str(match.get("exact", ""))
    viewport = observation.get("viewport") or {}
    anchor_box = _anchor_region(anchor, viewport)
    for region in observation.get("text_regions", []) or []:
        if not isinstance(region, Mapping) or str(region.get("text", "")).strip() != expected:
            continue
        confidence = region.get("confidence")
        if not isinstance(confidence, (int, float)) or float(confidence) < min_confidence:
            continue
        bbox = region.get("bbox")
        if anchor_box and bbox and not _boxes_intersect(_bbox_center_point(bbox), anchor_box):
            continue
        contaminated = _contaminated_by(bbox, overlays) if bbox else []
        return {
            "matched": True,
            "evidence_ids": [str(region.get("id", ""))],
            "overlay_contaminated": bool(contaminated),
            "overlay_ids": contaminated,
            "note": "",
        }
    return {"matched": False, "evidence_ids": [], "overlay_contaminated": False,
            "note": f"text {expected!r} not found"}


def _bbox_center_point(bbox: Iterable[float]) -> list[float]:
    x, y, w, h = (float(v) for v in bbox)
    return [x + w / 2, y + h / 2, 1, 1]


def _evaluate_element(anchor: Mapping[str, Any], grounded: list[Mapping[str, Any]],
                      overlays: list[dict[str, Any]],
                      min_confidence: float) -> dict[str, Any]:
    match = anchor.get("match") or {}
    expected = str(match.get("exact", ""))
    for element in grounded:
        if element.get("text_evidence_status") != "MATCHED":
            continue
        for evidence in element.get("text_evidence", []) or []:
            if str(evidence.get("text", "")).strip() != expected:
                continue
            if float(evidence.get("confidence", 0)) < min_confidence:
                continue
            bbox = element.get("bbox")
            contaminated = _contaminated_by(bbox, overlays) if bbox else []
            return {
                "matched": True,
                "evidence_ids": [str(element.get("element_id", ""))],
                "overlay_contaminated": bool(contaminated),
                "overlay_ids": contaminated,
                "note": "",
            }
    return {"matched": False, "evidence_ids": [], "overlay_contaminated": False,
            "note": f"element text {expected!r} not grounded"}


def _evaluate_element_density(anchor: Mapping[str, Any], observation: Mapping[str, Any]) -> dict[str, Any]:
    viewport = observation.get("viewport") or {}
    anchor_box = _anchor_region(anchor, viewport)
    count = 0
    for candidate in observation.get("interaction_candidates", []) or []:
        if not isinstance(candidate, Mapping) or candidate.get("bbox") is None:
            continue
        if anchor_box and not _boxes_intersect(_bbox_center_point(candidate["bbox"]), anchor_box):
            continue
        count += 1
    minimum = int(anchor.get("min_count", 1))
    return {"matched": count >= minimum, "evidence_ids": [],
            "overlay_contaminated": False,
            "note": f"density={count} threshold={minimum}"}


def evaluate_home_identity(
    observation: Mapping[str, Any],
    grounded_elements: Mapping[str, Any] | list[Mapping[str, Any]] | None,
    spec: Mapping[str, Any],
    field_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate the identity gate. Pure JSON function; raises on nothing.

    ``field_projection`` is the driver's current projection (possibly human
    clarified): field_value anchors prefer it as their evidence source, so a
    clarification with user_reported provenance can complete identity while
    still never being confused with vision evidence.
    """
    reasons: list[str] = []
    viewport = observation.get("viewport") or {}
    if not isinstance(viewport.get("width"), int) or not isinstance(viewport.get("height"), int):
        return _verdict(HOME_AMBIGUOUS, ["viewport_missing"], observation, [], [], [], spec)

    sensor_status = observation.get("sensor_status") or {}
    sensor_blind = bool(sensor_status.get("paddle_ocr_empty")) or \
        sensor_status.get("text_sensor") == "none"

    overlays = _overlays(observation)
    min_confidence = float(spec.get("min_anchor_confidence", 0.6))
    grounded: list[Mapping[str, Any]] = (
        list(grounded_elements) if isinstance(grounded_elements, list)
        else list((grounded_elements or {}).get("elements", []))
    )

    positives: list[dict[str, Any]] = []
    negatives: list[dict[str, Any]] = []
    unknown_kinds: list[str] = []

    for anchor in spec.get("negative_anchors", []) or []:
        if not isinstance(anchor, Mapping) or anchor.get("kind") not in _ANCHOR_KINDS:
            unknown_kinds.append(str(anchor.get("anchor_id", "?"))
                                 if isinstance(anchor, Mapping) else "?")
            continue
        result = _evaluate_anchor(anchor, observation, grounded, overlays, min_confidence)
        result["anchor_id"] = anchor.get("anchor_id", "")
        negatives.append(result)

    if sensor_blind:
        reasons.append("sensor_blind")

    contradicting = [n for n in negatives
                     if n["matched"] and not n.get("overlay_contaminated")]
    if contradicting:
        return _verdict(NOT_HOME, ["contradicting_evidence"], observation,
                        [], contradicting, _overlay_interference(overlays, positives, negatives), spec,
                        unknown_kinds)
    if unknown_kinds:
        reasons.append("unknown_anchor_kind:" + ",".join(sorted(unknown_kinds)))
    if sensor_blind:
        return _verdict(HOME_AMBIGUOUS, reasons, observation, [], negatives,
                        _overlay_interference(overlays, positives, negatives), spec, unknown_kinds)

    for anchor in spec.get("positive_anchors", []) or []:
        if not isinstance(anchor, Mapping) or anchor.get("kind") not in _ANCHOR_KINDS:
            unknown_kinds.append(str(anchor.get("anchor_id", "?"))
                                 if isinstance(anchor, Mapping) else "?")
            continue
        result = _evaluate_anchor(anchor, observation, grounded, overlays, min_confidence,
                                  field_projection=field_projection)
        result["anchor_id"] = anchor.get("anchor_id", "")
        result["required"] = bool(anchor.get("required", False))
        positives.append(result)

    if unknown_kinds and not any(r.startswith("unknown_anchor_kind") for r in reasons):
        reasons.append("unknown_anchor_kind:" + ",".join(sorted(unknown_kinds)))

    required = [p for p in positives if p["required"]]
    optional = [p for p in positives if not p["required"]]
    contaminated_required = [p for p in required if p.get("overlay_contaminated")]
    confirmed_required = [p for p in required
                          if p["matched"] and not p.get("overlay_contaminated")]
    human_only_required = [p for p in required if p.get("human_provenance")]

    interference = _overlay_interference(overlays, positives, negatives)
    if contaminated_required:
        reasons.append("overlay_contaminated_required:" +
                       ",".join(sorted(p["anchor_id"] for p in contaminated_required)))
    if human_only_required:
        reasons.append("identity_evidence_not_visual:" +
                       ",".join(sorted(p["anchor_id"] for p in human_only_required)))

    # Requirement: EVERY required identity anchor needs visual evidence.
    # Human-supplied values can complete the business projection, but a frame
    # whose required anchors are all human-provenanced is never CONFIRMED.
    if len(required) > 0 and len(human_only_required) == len(required):
        return _verdict(HOME_AMBIGUOUS,
                        (reasons if reasons else []) + ["identity_evidence_not_visual"],
                        observation, positives, negatives, interference, spec, unknown_kinds)
    if len(required) > 0 and len(confirmed_required) == len(required):
        if contaminated_required:
            return _verdict(HOME_AMBIGUOUS, reasons or ["overlay_contaminated_required"],
                            observation, positives, negatives, interference, spec, unknown_kinds)
        return _verdict(HOME_CONFIRMED, reasons, observation, positives, negatives,
                        interference, spec, unknown_kinds)
    if confirmed_required or any(p["matched"] for p in optional):
        reasons.append("partial_home_evidence")
    elif not reasons:
        reasons.append("no_positive_evidence")
    return _verdict(HOME_AMBIGUOUS, reasons, observation, positives, negatives,
                    interference, spec, unknown_kinds)


def _evaluate_anchor(anchor: Mapping[str, Any], observation: Mapping[str, Any],
                     grounded: list[Mapping[str, Any]], overlays: list[dict[str, Any]],
                     min_confidence: float,
                     field_projection: Mapping[str, Any] | None = None) -> dict[str, Any]:
    kind = anchor.get("kind")
    if kind == "field_value":
        return _evaluate_field_value(anchor, observation, grounded,
                                     observation.get("viewport") or {}, overlays, min_confidence,
                                     field_projection)
    if kind == "text":
        return _evaluate_text(anchor, observation, overlays, min_confidence)
    if kind == "element":
        return _evaluate_element(anchor, grounded, overlays, min_confidence)
    if kind == "element_density":
        return _evaluate_element_density(anchor, observation)
    return {"matched": False, "evidence_ids": [], "note": "unknown anchor kind"}


def _overlay_interference(overlays: list[dict[str, Any]],
                          positives: list[dict[str, Any]],
                          negatives: list[dict[str, Any]]) -> list[dict[str, Any]]:
    interference: list[dict[str, Any]] = []
    for entry in positives + negatives:
        if entry.get("overlay_contaminated"):
            interference.append({
                "overlay_ids": entry.get("overlay_ids", []),
                "contaminated_anchor": entry.get("anchor_id", ""),
            })
    return interference


def _verdict(verdict: str, reasons: list[str], observation: Mapping[str, Any],
             positives: list[dict[str, Any]], negatives: list[dict[str, Any]],
             interference: list[dict[str, Any]], spec: Mapping[str, Any],
             unknown_kinds: list[str]) -> dict[str, Any]:
    sensor_status = observation.get("sensor_status") or {}
    return {
        "contract": CONTRACT,
        "verdict": verdict,
        "observation_id": str(observation.get("observation_id", "")),
        "reasons": reasons or (["unknown_anchor_kind"] if unknown_kinds else []),
        "positive_evidence": positives,
        "negative_evidence": negatives,
        "overlay_interference": interference,
        "sensor_gates": {
            "text_sensor": sensor_status.get("text_sensor"),
            "paddle_ocr_empty": bool(sensor_status.get("paddle_ocr_empty")),
        },
        "spec_version": str(spec.get("contract", "unknown")),
    }


__all__ = [
    "CONTRACT",
    "HOME_CONFIRMED",
    "HOME_AMBIGUOUS",
    "NOT_HOME",
    "evaluate_home_identity",
]

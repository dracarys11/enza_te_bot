"""Read-only HOME evidence capture and ROI teaching; no gameplay policy."""
from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from pathlib import Path
import re
from typing import Callable

import cv2
import numpy as np
import pyautogui

from config_store import backup_and_write_config
from ui_preview import select_scaled_roi


BASE_DIR = Path(__file__).resolve().parent
FIELDS = ("season", "weeks_remaining", "fan_gap_to_target", "stamina")
WEEKS_TEMPLATE_DIR = BASE_DIR / "templates" / "home_weeks_digits"
pyautogui.FAILSAFE = True


@dataclass(frozen=True)
class HomeObservation:
    """Validated HOME facts only; no policy or cumulative-fan inference."""
    season: int
    weeks_remaining: int
    fan_gap_to_target: int
    fan_target_achieved: bool = False
    stamina_adequate: bool = True
    # Set only by the trusted validated-observation pipeline.  ``compare=False``
    # keeps provenance out of tuple consistency while preserving it for the
    # HOME execution boundary.
    provenance: object | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class HomeObservationUnreadable:
    """Structured, evidence-preserving failure rather than a guessed value."""
    reasons: dict[str, str]
    raw_samples: list[dict[str, object]]
    screenshots: list[str]


@dataclass(frozen=True)
class WeekLearningEvidence:
    """The narrow, verified facts required to label one new week digit."""
    previous_week: int
    previous_season: int
    action_name: str | None
    action_sent: bool
    action_completed_at_home: bool
    consumes_one_week: bool
    boundary_season: int | None


@dataclass(frozen=True)
class FreshHomeCapture:
    """A no-click HOME capture taken only after candidate evidence was saved."""
    image: object
    state: str
    season: int | None
    screenshot: str


_NUMBER_TOKEN = re.compile(r"(?<![\d,\-])(?:\d{1,3}(?:,\d{3})+|\d+)(?![\d,])")
_FAN_GAP_TOKEN = re.compile(
    r"(?<![\d,.\-])(?:\d{1,3}(?P<separator>[,.])\d{3}(?:(?P=separator)\d{3})*|\d+)(?![\d,.])"
)


def numeric_candidates(raw: str) -> tuple[list[int], str | None]:
    """Return complete numeric tokens only; malformed comma groups are rejected."""
    tokens = _NUMBER_TOKEN.findall(raw)
    if not tokens:
        return [], "no numeric candidate"
    values: list[int] = []
    for token in tokens:
        if "," in token and not re.fullmatch(r"\d{1,3}(?:,\d{3})+", token):
            return [], f"malformed numeric token {token!r}"
        values.append(int(token.replace(",", "")))
    if len(values) != 1:
        return [], f"ambiguous numeric candidates {values}"
    return values, None


def parse_single_integer(raw: str, field: str, lower: int, upper: int | None) -> tuple[int | None, str | None]:
    values, error = numeric_candidates(raw)
    if error:
        return None, error
    value = values[0]
    if value < lower or (upper is not None and value > upper):
        return None, f"{field} value {value} outside configured range {lower}..{upper if upper is not None else '∞'}"
    return value, None


def parse_season(raw: str) -> tuple[int | None, str | None]:
    return parse_single_integer(raw, "season", 1, 4)


def parse_weeks_remaining(raw: str, accepted_range: list[int]) -> tuple[int | None, str | None]:
    if not isinstance(accepted_range, list) or len(accepted_range) != 2:
        return None, "weeks_remaining range is missing or invalid"
    return parse_single_integer(raw, "weeks_remaining", int(accepted_range[0]), int(accepted_range[1]))


def parse_fan_gap_to_target(raw: str) -> tuple[int | None, str | None]:
    """Parse one complete integer or consistently grouped comma/period token.

    OCR sometimes renders a thousands comma as a period.  This accepts only a
    complete token with valid, consistent three-digit grouping; it never joins
    separate numeric fragments.
    """
    tokens = [match.group(0) for match in _FAN_GAP_TOKEN.finditer(raw)]
    if not tokens:
        return None, "no numeric candidate"
    if len(tokens) != 1:
        return None, f"ambiguous numeric candidates {tokens}"
    token = tokens[0]
    value = int(token.replace(",", "").replace(".", ""))
    if value < 0:
        return None, "fan_gap_to_target value must be non-negative"
    return value, None


def detect_fan_target_clear(crop, settings: dict | None) -> dict[str, object]:
    """Recognize explicit red CLEAR artwork; blank OCR is never sufficient."""
    if not isinstance(settings, dict):
        return {"visible": False, "reason": "clear marker configuration missing"}
    rgb = np.array(crop.convert("RGB"))
    if rgb.size == 0:
        return {"visible": False, "reason": "empty fan target crop"}
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    hue = hsv[:, :, 0]
    mask = (((hue <= int(settings.get("hue_low_max", 12))) |
             (hue >= int(settings.get("hue_high_min", 170)))) &
            (hsv[:, :, 1] >= int(settings.get("saturation_min", 120))) &
            (hsv[:, :, 2] >= int(settings.get("value_min", 150)))).astype(np.uint8)
    red_fraction = float(mask.mean())
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask * 255)
    image_area = float(rgb.shape[0] * rgb.shape[1])
    minimum_area = image_area * float(settings.get("minimum_component_area_fraction", 0.005))
    component_count = sum(1 for index in range(1, count) if float(stats[index, cv2.CC_STAT_AREA]) >= minimum_area)
    visible = (red_fraction >= float(settings.get("minimum_red_fraction", 0.03)) and
               component_count >= int(settings.get("minimum_component_count", 4)))
    return {"visible": visible, "red_fraction": red_fraction, "component_count": component_count,
            "source": "home_fan_target_clear_visual_marker"}


def detect_stamina_adequate(crop, settings: dict | None = None) -> dict[str, object]:
    """Detect binary stamina adequacy (>=50% vs <50%) from taught stamina bar crop.

    Returns structured visual evidence; blank or ambiguous evidence fails closed.
    """
    settings = settings or {}
    if crop is None:
        return {"adequate": None, "reason": "stamina crop is None"}
    rgb = np.array(crop.convert("RGB")) if hasattr(crop, "convert") else np.array(crop)
    if rgb.size == 0 or rgb.shape[0] < 2 or rgb.shape[1] < 2:
        return {"adequate": None, "reason": "empty stamina crop"}

    sat_min = int(settings.get("saturation_min", 40))
    val_min = int(settings.get("value_min", 40))
    min_start_fill = float(settings.get("min_start_fill", 0.15))
    midpoint_col_threshold = float(settings.get("midpoint_col_threshold", 0.20))

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h = hsv[:, :, 0]
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]

    # Active stamina bar colors: green, yellow/orange, red
    active = (
        ((h >= 35) & (h <= 85) & (s >= sat_min) & (v >= val_min)) |
        ((h >= 15) & (h < 35) & (s >= sat_min) & (v >= val_min)) |
        (((h < 15) | (h >= 165)) & (s >= sat_min) & (v >= val_min))
    )

    col_fill = active.mean(axis=0)
    w = col_fill.shape[0]
    left_fill = float(col_fill[:max(1, int(0.10 * w))].mean())
    mid_fill = float(col_fill[int(0.45 * w):max(int(0.45 * w) + 1, int(0.55 * w))].mean())
    overall_fill = float(active.mean())

    if left_fill < min_start_fill and overall_fill < 0.05:
        return {
            "adequate": None,
            "reason": "no active stamina bar fill detected (blank/unreadable)",
            "left_fill": left_fill,
            "mid_fill": mid_fill,
            "overall_fill": overall_fill,
            "source": "home_stamina_adequate_visual_marker",
        }

    adequate = bool(mid_fill >= midpoint_col_threshold)
    return {
        "adequate": adequate,
        "left_fill": left_fill,
        "mid_fill": mid_fill,
        "overall_fill": overall_fill,
        "source": "home_stamina_adequate_visual_marker",
    }


def normalized_capture_roi(x: int, y: int, width: int, height: int, window: dict, capture_scale: dict) -> list[float]:
    """Map a physical-pixel crop back to the normalized logical game window."""
    physical_width = float(window["width"]) * float(capture_scale["x"])
    physical_height = float(window["height"]) * float(capture_scale["y"])
    roi = [x / physical_width, y / physical_height,
           (x + width) / physical_width, (y + height) / physical_height]
    if not (0.0 <= roi[0] < roi[2] <= 1.0 and 0.0 <= roi[1] < roi[3] <= 1.0):
        raise ValueError("Selected HOME observation ROI lies outside the dynamic game window.")
    return [round(value, 6) for value in roi]


def _select_field(image, field: str, window: dict, capture_scale: dict) -> list[float] | None:
    readable_name = field.replace("_", " ")
    print(f"Select only the current {readable_name} value. Enter/Space confirms; Esc or c cancels.")
    (x, y, width, height), preview_box, original_size, preview_size, scale, screen_size = select_scaled_roi(
        image, f"HOME observation: {readable_name}"
    )
    if width <= 0 or height <= 0:
        return None
    roi = normalized_capture_roi(x, y, width, height, window, capture_scale)
    print(f"{field}: original={original_size}, preview={preview_size}, screen={screen_size}, scale={scale:.6f}")
    print(f"{field}: preview_box={preview_box}, normalized_roi={roi}")
    return roi


def capture_home_observation_rois(image, window: dict, config: dict) -> dict | None:
    """Gather all required HOME ROIs, then atomically save them once.

    This function captures no templates and sends no game input. Cancelling any
    field aborts before configuration mutation, leaving prior ROI evidence intact.
    """
    capture_scale = config.get("capture_scale")
    if not isinstance(capture_scale, dict) or not capture_scale.get("x") or not capture_scale.get("y"):
        raise ValueError("Missing dynamic capture scale; refusing HOME ROI capture.")
    selected: dict[str, list[float]] = {}
    for field in FIELDS:
        roi = _select_field(image, field, window, capture_scale)
        if roi is None:
            print("Cancelled: no HOME observation configuration was changed.")
            return None
        selected[field] = roi

    perception = config.setdefault("perception", {})
    observation = perception.setdefault("home_observation", {})
    observation["retries"] = 3
    observation["retry_interval_ms"] = 250
    for field, roi in selected.items():
        observation[field] = {"roi": roi}
    observation["season"]["range"] = [1, 4]
    # Only a structural guard: existing evidence establishes a non-negative
    # weekly display, not a gameplay-policy upper bound.
    observation["weeks_remaining"]["range"] = [0, 99]

    # Runtime geometry is recalculated per capture and is never persistent evidence.
    config["game_window"] = None
    config.pop("capture_scale", None)
    backup_path = backup_and_write_config(BASE_DIR / "config.json", config)
    print(f"HOME observation ROIs saved in perception.home_observation\nconfig backup: {backup_path}")
    return {"rois": selected, "backup": str(backup_path)}


def capture_home_observation_roi(image, window: dict, config: dict, field: str) -> dict | None:
    """Re-teach exactly one HOME observation ROI without touching other fields.

    This is evidence capture only: it never creates a template or sends game
    input.  Cancelling leaves the existing configuration unchanged.
    """
    if field not in FIELDS:
        raise ValueError(f"Unknown HOME observation field: {field}")
    capture_scale = config.get("capture_scale")
    if not isinstance(capture_scale, dict) or not capture_scale.get("x") or not capture_scale.get("y"):
        raise ValueError("Missing dynamic capture scale; refusing HOME ROI capture.")

    roi = _select_field(image, field, window, capture_scale)
    if roi is None:
        print("Cancelled: no HOME observation configuration was changed.")
        return None

    observation = config.setdefault("perception", {}).setdefault("home_observation", {})
    field_spec = observation.setdefault(field, {})
    field_spec["roi"] = roi

    # Runtime geometry is recalculated per capture and is never persistent evidence.
    config["game_window"] = None
    config.pop("capture_scale", None)
    backup_path = backup_and_write_config(BASE_DIR / "config.json", config)
    print(f"HOME observation ROI saved: perception.home_observation.{field}.roi\nconfig backup: {backup_path}")
    return {"field": field, "roi": roi, "backup": str(backup_path)}


def _crop_normalized_roi(image, roi: list[float]):
    left, top, right, bottom = roi
    return image.crop((round(left * image.width), round(top * image.height),
                       round(right * image.width), round(bottom * image.height)))


def capture_home_week_digit_template(image, config: dict, digit: str) -> dict:
    """Teach one observed weeks digit from the existing tight ROI; never clicks."""
    if not re.fullmatch(r"\d", digit):
        raise ValueError("HOME weeks digit must be one character in 0..9.")
    roi = configured_rois(config)["weeks_remaining"]
    digit_dir = WEEKS_TEMPLATE_DIR / digit
    legacy_destination = WEEKS_TEMPLATE_DIR / f"{digit}.png"
    crop = _crop_normalized_roi(image, roi)
    if crop.width <= 0 or crop.height <= 0:
        raise ValueError("Configured weeks_remaining ROI produced an empty crop.")

    # Capture the observed visual evidence before registering it.  If config
    # writing later fails, the unregistered PNG is harmless and never active.
    existing = list(digit_dir.glob("exemplar_*.png")) if digit_dir.exists() else []
    # Preserve the historical first-capture filename; subsequent captures
    # append under digit/ as exemplars.
    if not existing and not legacy_destination.exists():
        destination = legacy_destination
    else:
        digit_dir.mkdir(parents=True, exist_ok=True)
        destination = digit_dir / f"exemplar_{len(existing)+1:03d}.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Reject near-identical teaching captures without replacing evidence.
    probe = cv2.cvtColor(np.array(crop.convert("RGB")), cv2.COLOR_RGB2GRAY)
    for prior in existing:
        old = cv2.imread(str(prior), cv2.IMREAD_GRAYSCALE)
        if old is not None and cv2.minMaxLoc(cv2.matchTemplate(probe, cv2.resize(old, (probe.shape[1], probe.shape[0])), cv2.TM_CCOEFF_NORMED))[1] >= 0.999:
            raise ValueError(f"Duplicate HOME weeks digit exemplar; kept existing {prior}")
    crop.save(destination)
    observation = config.setdefault("perception", {}).setdefault("home_observation", {})
    matching = observation.setdefault("weeks_remaining", {}).setdefault("template_matching", {})
    matching.setdefault("directory", "templates/home_weeks_digits")
    matching.setdefault("confidence_threshold", 0.90)
    matching.setdefault("min_margin", 0.05)
    current = matching.setdefault("digits", {})
    values = current.get(digit, [])
    if isinstance(values, str): values = [values]
    rel = destination.relative_to(WEEKS_TEMPLATE_DIR)
    current[digit] = list(values) + [str(rel)] if values else str(rel)
    config["game_window"] = None
    config.pop("capture_scale", None)
    backup_path = backup_and_write_config(BASE_DIR / "config.json", config)
    return {"digit": digit, "template": str(destination), "roi": roi, "backup": str(backup_path)}


def _quarantine_week_candidate(candidate: Path, reason: str) -> str:
    """Keep rejected evidence without making it an active digit template."""
    if not candidate.exists():
        return ""
    quarantine = candidate.parent / "quarantine"
    quarantine.mkdir(exist_ok=True)
    safe_reason = re.sub(r"[^a-z0-9_]+", "_", reason.lower()).strip("_") or "rejected"
    target = quarantine / f"{candidate.stem}_{safe_reason}{candidate.suffix}"
    suffix = 1
    while target.exists():
        target = quarantine / f"{candidate.stem}_{safe_reason}_{suffix}{candidate.suffix}"
        suffix += 1
    candidate.replace(target)
    return str(target)


def auto_learn_week_digit_from_progression(candidate_image, config: dict, evidence: WeekLearningEvidence,
                                            fresh_home_capture: Callable[[], FreshHomeCapture]) -> dict[str, object]:
    """Safely label W-1 only from a verified one-week room transaction.

    The candidate is not added to config until a *new* same-season HOME capture
    independently matches it above the existing threshold and margin.
    """
    details: dict[str, object] = {
        "previous_week": evidence.previous_week,
        "action": evidence.action_name,
        "action_sent": evidence.action_sent,
        "action_completed_at_home": evidence.action_completed_at_home,
        "consumes_one_week": evidence.consumes_one_week,
        "boundary_season": evidence.boundary_season,
    }
    inferred = evidence.previous_week - 1
    details["inferred_week"] = inferred
    if (not evidence.action_sent or not evidence.action_completed_at_home or not evidence.consumes_one_week or
            evidence.action_name != "vocal_lesson"):
        details.update({"status": "SKIPPED", "reason": "no_verified_week_consuming_action"})
        return details
    if evidence.boundary_season != evidence.previous_season:
        details.update({"status": "SKIPPED", "reason": "season_boundary_or_unreadable_boundary_season"})
        return details
    weeks_spec = config.get("perception", {}).get("home_observation", {}).get("weeks_remaining", {})
    accepted_range = weeks_spec.get("range")
    if not isinstance(accepted_range, list) or len(accepted_range) != 2 or not (int(accepted_range[0]) <= inferred <= int(accepted_range[1])):
        details.update({"status": "SKIPPED", "reason": "inferred_week_outside_configured_range"})
        return details
    matching = weeks_spec.get("template_matching")
    if not isinstance(matching, dict) or not isinstance(matching.get("digits"), dict):
        details.update({"status": "SKIPPED", "reason": "week_template_matching_not_configured"})
        return details
    digits = matching["digits"]
    final = WEEKS_TEMPLATE_DIR / f"{inferred}.png"
    if str(inferred) in digits or final.exists():
        details.update({"status": "SKIPPED", "reason": "inferred_digit_template_already_exists"})
        return details

    roi = configured_rois(config)["weeks_remaining"]
    current_crop = _crop_normalized_roi(candidate_image, roi)
    existing = recognize_week_digit_template(current_crop, matching)
    details["existing_template_scores"] = existing.get("candidate_scores", {})
    if existing.get("selected_raw"):
        details.update({"status": "SKIPPED", "reason": "existing_confident_digit_blocks_learning",
                        "existing_digit": existing["selected_raw"]})
        return details

    candidates = WEEKS_TEMPLATE_DIR / "candidates"
    candidates.mkdir(parents=True, exist_ok=True)
    candidate = candidates / f"{__import__('datetime').datetime.now():%Y%m%d_%H%M%S_%f}_week_{inferred}.png"
    current_crop.save(candidate)
    details["candidate_path"] = str(candidate)

    try:
        fresh = fresh_home_capture()
    except Exception as error:
        details.update({"status": "UNREADABLE", "reason": f"fresh_home_capture_failed: {error}",
                        "quarantine_path": _quarantine_week_candidate(candidate, "fresh_capture_failed")})
        return details
    details["fresh_screenshot"] = fresh.screenshot
    if fresh.state != "HOME" or fresh.season != evidence.previous_season:
        details.update({"status": "UNREADABLE", "reason": "fresh_home_or_same_season_verification_failed",
                        "fresh_state": fresh.state, "fresh_season": fresh.season,
                        "quarantine_path": _quarantine_week_candidate(candidate, "fresh_boundary_failed")})
        return details

    provisional = deepcopy(matching)
    provisional["digits"] = dict(matching["digits"])
    provisional["digits"][str(inferred)] = f"candidates/{candidate.name}"
    verification_crop = _crop_normalized_roi(fresh.image, roi)
    verification = recognize_week_digit_template(verification_crop, provisional)
    details["verification_scores"] = verification.get("candidate_scores", {})
    details["verification_score"] = verification.get("top_score")
    details["verification_margin"] = verification.get("margin")
    if verification.get("selected_raw") != str(inferred):
        details.update({"status": "UNREADABLE", "reason": "candidate_verification_failed",
                        "quarantine_path": _quarantine_week_candidate(candidate, "verification_failed")})
        return details
    existing_fresh = recognize_week_digit_template(verification_crop, matching)
    if existing_fresh.get("selected_raw") and existing_fresh.get("selected_raw") != str(inferred):
        details.update({"status": "UNREADABLE", "reason": "fresh_confident_existing_digit_conflict",
                        "existing_digit": existing_fresh.get("selected_raw"),
                        "quarantine_path": _quarantine_week_candidate(candidate, "existing_conflict")})
        return details
    if final.exists():  # Last line of defense against races/overwrites.
        details.update({"status": "UNREADABLE", "reason": "inferred_digit_template_already_exists",
                        "quarantine_path": _quarantine_week_candidate(candidate, "already_exists")})
        return details

    candidate.replace(final)
    matching["digits"][str(inferred)] = f"{inferred}.png"
    config["game_window"] = None
    config.pop("capture_scale", None)
    try:
        backup_path = backup_and_write_config(BASE_DIR / "config.json", config)
    except Exception as error:
        details.update({"status": "UNREADABLE", "reason": f"atomic_config_commit_failed: {error}",
                        "quarantine_path": _quarantine_week_candidate(final, "config_commit_failed")})
        return details
    details.update({"status": "COMMITTED", "reason": "verified_w_minus_one_template",
                    "template_path": str(final), "config_backup": str(backup_path)})
    return details


def _ocr_text(crop, config: str) -> str:
    """Small boundary kept patchable for offline OCR-path tests."""
    import pytesseract
    return pytesseract.image_to_string(crop, config=config).strip()


def recognize_week_digit_template(crop, matching: dict | None) -> dict[str, object] | None:
    """Score all taught week-digit templates; no OCR fallback exists for weeks."""
    if not isinstance(matching, dict) or not matching.get("digits"):
        return {"selected_raw": "", "candidate_scores": {},
                "recognition_error": "no configured HOME weeks digit templates"}
    try:
        threshold = float(matching["confidence_threshold"])
        min_margin = float(matching["min_margin"])
        digits = matching["digits"]
        directory = matching["directory"]
    except (KeyError, TypeError, ValueError) as error:
        return {"selected_raw": "", "candidate_scores": {}, "recognition_error": f"invalid template configuration: {error}"}
    if not (0.0 <= threshold <= 1.0 and 0.0 <= min_margin <= 1.0) or not isinstance(digits, dict) or not isinstance(directory, str):
        return {"selected_raw": "", "candidate_scores": {}, "recognition_error": "invalid template threshold, margin, or digit mapping"}

    root = (BASE_DIR / directory).resolve()
    templates_root = (BASE_DIR / "templates").resolve()
    if templates_root not in root.parents and root != templates_root:
        return {"selected_raw": "", "candidate_scores": {}, "recognition_error": "template directory must be inside templates/"}
    frame = cv2.cvtColor(np.array(crop.convert("RGB")), cv2.COLOR_RGB2GRAY)
    scores: dict[str, float] = {}
    missing: list[str] = []
    for digit, filenames in digits.items():
        if not isinstance(digit, str) or not re.fullmatch(r"\d", digit):
            missing.append(str(digit))
            continue
        if isinstance(filenames, str): filenames = [filenames]
        best = None
        for filename in filenames if isinstance(filenames, list) else []:
            path = root / filename
            template = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if path.is_file() else None
            if template is None or template.size == 0: continue
            resized = cv2.resize(template, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_CUBIC)
            score = float(cv2.minMaxLoc(cv2.matchTemplate(frame, resized, cv2.TM_CCOEFF_NORMED))[1])
            best = score if best is None else max(best, score)
        if best is None:
            missing.append(digit)
        else:
            scores[digit] = best
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked:
        return {"selected_raw": "", "candidate_scores": scores,
                "recognition_error": "missing or unreadable configured digit templates", "missing_templates": missing}
    top_digit, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else None
    margin = None if second_score is None else top_score - second_score
    accepted = top_score > threshold and (margin is None or margin > min_margin)
    return {
        "selected_raw": top_digit if accepted else "",
        "candidate_scores": scores,
        "top_digit": top_digit,
        "top_score": top_score,
        "top2_score": second_score,
        "margin": margin,
        "threshold": threshold,
        "min_margin": min_margin,
        "recognition_error": None if accepted else "low confidence or ambiguous top digit",
        "missing_templates": missing,
    }


def smoke_ocr(image, rois: dict[str, list[float]], *,
              weeks_template_matching: dict | None = None,
              fan_target_clear_settings: dict | None = None,
              stamina_settings: dict | None = None) -> tuple[dict[str, str], dict[str, dict[str, object]]]:
    """Return field diagnostics; weeks uses only taught OpenCV digit templates."""
    if any(field not in {"weeks_remaining", "stamina"} for field in rois):
        try:
            import pytesseract  # noqa: F401 - check availability before generic OCR.
        except ImportError:
            unavailable = {field: "<pytesseract unavailable>" for field in rois}
            return unavailable, {field: {"generic_raw": unavailable[field], "digit_raw": None,
                                         "selected_raw": unavailable[field]} for field in rois}
    else:
        pytesseract = None  # noqa: F841 - documents that no OCR backend is needed.
    output: dict[str, str] = {}
    diagnostics: dict[str, dict[str, object]] = {}
    for field, roi in rois.items():
        left, top, right, bottom = roi
        crop = _crop_normalized_roi(image, roi)
        try:
            if field == "weeks_remaining":
                template_result = recognize_week_digit_template(crop, weeks_template_matching)
                selected_raw = str(template_result["selected_raw"])
                output[field] = selected_raw
                diagnostics[field] = {
                    "method": "opencv_digit_template",
                    "generic_raw": None,
                    "digit_raw": None,
                    "preprocessed_raw": {},
                    "selected_raw": selected_raw,
                    "selection_error": template_result.get("recognition_error"),
                    "debug_paths": [],
                    "template": template_result,
                }
                continue
            if field == "stamina":
                stamina_result = detect_stamina_adequate(crop, stamina_settings)
                selected_raw = "adequate" if stamina_result.get("adequate") is True else ("low" if stamina_result.get("adequate") is False else "")
                output[field] = selected_raw
                diagnostics[field] = {
                    "method": "home_stamina_adequate_visual_marker",
                    "generic_raw": None,
                    "digit_raw": None,
                    "preprocessed_raw": {},
                    "selected_raw": selected_raw,
                    "selection_error": stamina_result.get("reason"),
                    "debug_paths": [],
                    "stamina": stamina_result,
                }
                continue
            generic_raw = _ocr_text(crop, "--psm 7")
            selected_raw = generic_raw
            output[field] = selected_raw
            diagnostics[field] = {
                "method": "tesseract",
                "generic_raw": generic_raw,
                "digit_raw": None,
                "preprocessed_raw": {},
                "selected_raw": selected_raw,
                "selection_error": None,
                "debug_paths": [],
            }
            if field == "fan_gap_to_target":
                diagnostics[field]["clear_marker"] = detect_fan_target_clear(crop, fan_target_clear_settings)
        except Exception as error:  # Diagnostic must never affect evidence capture.
            failure = f"<OCR smoke test failed: {error}>"
            output[field] = failure
            diagnostics[field] = {"method": "tesseract", "generic_raw": failure, "digit_raw": None, "preprocessed_raw": {},
                                  "selected_raw": failure, "selection_error": None, "debug_paths": []}
    return output, diagnostics


def configured_rois(config: dict) -> dict[str, list[float]]:
    """Return the taught ROI evidence or fail closed before OCR."""
    observation = config.get("perception", {}).get("home_observation", {})
    result: dict[str, list[float]] = {}
    for field in FIELDS:
        roi = observation.get(field, {}).get("roi")
        if not isinstance(roi, list) or len(roi) != 4 or not all(isinstance(value, (int, float)) for value in roi):
            raise ValueError(f"Missing or invalid configured HOME ROI for {field}.")
        if not (0.0 <= roi[0] < roi[2] <= 1.0 and 0.0 <= roi[1] < roi[3] <= 1.0):
            raise ValueError(f"Configured HOME ROI for {field} lies outside the game window.")
        result[field] = [float(value) for value in roi]
    return result


def parse_home_sample(raw: dict[str, str], config: dict, *,
                      fan_target_achieved: bool = False,
                      stamina_adequate: bool | None = None) -> tuple[HomeObservation | None, dict[str, str]]:
    """Parse one OCR sample conservatively; all fields must be individually valid."""
    observation = config["perception"]["home_observation"]
    season, season_error = parse_season(raw.get("season", ""))
    weeks, weeks_error = parse_weeks_remaining(raw.get("weeks_remaining", ""), observation["weeks_remaining"].get("range"))
    if fan_target_achieved:
        gap, gap_error = 0, None
    else:
        gap, gap_error = parse_fan_gap_to_target(raw.get("fan_gap_to_target", ""))
    stamina_error = None
    if "stamina" in observation:
        if stamina_adequate is None:
            if raw.get("stamina") == "adequate":
                stamina_adequate = True
            elif raw.get("stamina") == "low":
                stamina_adequate = False
            else:
                stamina_error = "stamina evidence is unreadable or ambiguous"
    else:
        stamina_adequate = True
    reasons = {field: error for field, error in {
        "season": season_error, "weeks_remaining": weeks_error, "fan_gap_to_target": gap_error,
        "stamina": stamina_error,
    }.items() if error}
    if reasons:
        return None, reasons
    return HomeObservation(season=season, weeks_remaining=weeks, fan_gap_to_target=gap,
                           fan_target_achieved=fan_target_achieved,
                           stamina_adequate=bool(stamina_adequate)), {}


def consistently_observed(samples: list[HomeObservation]) -> HomeObservation | None:
    """Commit only a tuple observed successfully at least twice."""
    counts: dict[HomeObservation, int] = {}
    for sample in samples:
        counts[sample] = counts.get(sample, 0) + 1
        if counts[sample] >= 2:
            return sample
    return None

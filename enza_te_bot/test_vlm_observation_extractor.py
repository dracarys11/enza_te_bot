import hashlib
import json

import pytest

from tools.vlm_observation_extractor import extract_observation


def _image(tmp_path):
    path = tmp_path / "frame.png"
    path.write_bytes(b"offline image fixture")
    return path


def test_observation_schema_valid(tmp_path):
    path = _image(tmp_path)
    result = extract_observation(path)
    assert set(result) == {"image", "sha256", "observation", "confidence", "vlm_status"}
    assert len(result["sha256"]) == 64
    assert set(result["observation"]) == {"state", "phase", "event_type", "visible_text", "visible_controls", "layout_family"}
    assert result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_unknown_state_allowed(tmp_path):
    result = extract_observation(_image(tmp_path))
    assert result["observation"]["state"] == "UNKNOWN"
    assert result["observation"]["phase"] == "UNKNOWN"
    assert result["vlm_status"] == "PENDING"


def test_no_authority_fields(tmp_path):
    result = extract_observation(_image(tmp_path))
    serialized = json.dumps(result)
    for field in ("authority_type", "planner_decision", "execution_permission", "action_allowed"):
        assert field not in serialized
    with pytest.raises(ValueError, match="forbidden authority fields"):
        extract_observation(_image(tmp_path), {"state": "WING_HOME", "action_allowed": True})


def test_visible_control_not_action_permission(tmp_path):
    result = extract_observation(_image(tmp_path), {
        "state": "SCHEDULE",
        "visible_controls": [{"class": "CONFIRM", "label": "決定", "status": "SEEN"}],
    })
    assert result["observation"]["visible_controls"][0]["status"] == "SEEN"
    assert "action_allowed" not in result
    assert "execution_permission" not in result

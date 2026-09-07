import json
from pathlib import Path


def test_all_six_cases_have_expected_contract():
    root = Path(__file__).parent / "cases"
    cases = sorted(root.glob("ARB*/case.json"))
    assert len(cases) == 6
    for path in cases:
        case = json.loads(path.read_text())
        assert {"case_id", "objective", "input_artifacts", "task_prompt", "expected_invariants", "grading_rules"} <= case.keys()
        assert (path.parent / "normal").is_dir()
        assert (path.parent / "adversarial").is_dir()

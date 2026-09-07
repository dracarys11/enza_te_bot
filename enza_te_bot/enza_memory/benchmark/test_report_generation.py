from evaluator.report import generate_report


def test_report_generation_contains_cases_and_average():
    report = generate_report([
        {"case_id": "ARB001_planner_authority", "status": "PASS", "score": {"total": 95}},
        {"case_id": "ARB002_observation_timeout", "status": "PASS", "score": {"total": 90}},
    ], "OfflineAgent", "2026-09-07")
    assert "# ENZA Reliability Benchmark" in report
    assert "ARB001_planner_authority: PASS 95" in report
    assert "Average: 92.5" in report

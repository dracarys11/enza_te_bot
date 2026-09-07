"""Regression tests for independent Produce run progress."""
import json
import tempfile
import unittest
from pathlib import Path

from season3_audition import required_reward
from run_state import load_runtime_config, resolve_run_state


class RunStateIsolationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "enza_memory").mkdir()
        self.config_path = self.root / "config.json"
        self.registry_path = self.root / "enza_memory" / "artifact_registry.json"
        self.config_path.write_text(json.dumps({
            "static": True,
            "run_state": {"season3": {
                "audition_40k_completed": True,
                "audition_50k_completed": True,
            }},
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_registry(self, active_run, runs) -> None:
        self.registry_path.write_text(json.dumps({
            "current_mainline": {"active_run": active_run}, "runs": runs,
        }), encoding="utf-8")

    def add_state(self, run_id: str, forty: bool, fifty: bool) -> Path:
        directory = self.root / "enza_memory" / "wing_runs" / run_id
        directory.mkdir(parents=True)
        path = directory / "runtime_state.json"
        path.write_text(json.dumps({"run_id": run_id, "run_state": {"season3": {
            "audition_40k_completed": forty,
            "audition_50k_completed": fifty,
        }}}), encoding="utf-8")
        return path

    def record(self, run_id: str, *, resume_allowed: bool = True) -> dict:
        return {
            "id": run_id, "path": f"enza_memory/wing_runs/{run_id}",
            "resume_allowed": resume_allowed, "resume_file": None,
        }

    def test_new_run_does_not_inherit_closed_run_40k_completion(self) -> None:
        closed, new = "CLOSED_RUN", "NEW_RUN"
        self.add_state(closed, True, False)
        self.write_registry(new, [self.record(closed, resume_allowed=False), self.record(new)])
        state = resolve_run_state(json.loads(self.registry_path.read_text()), base_dir=self.root)
        self.assertFalse(state["season3"]["audition_40k_completed"])

    def test_new_run_does_not_skip_50k_from_closed_run(self) -> None:
        closed, new = "CLOSED_RUN", "NEW_RUN"
        self.add_state(closed, True, True)
        self.write_registry(new, [self.record(closed, resume_allowed=False), self.record(new)])
        state = resolve_run_state(json.loads(self.registry_path.read_text()), base_dir=self.root)
        state["season3"]["audition_40k_completed"] = True
        self.assertEqual(required_reward(state), 50000)

    def test_resume_exact_run_preserves_matching_local_progress(self) -> None:
        run_id = "ACTIVE_RUN"
        self.add_state(run_id, True, False)
        self.write_registry(run_id, [self.record(run_id)])
        state = resolve_run_state(
            json.loads(self.registry_path.read_text()), base_dir=self.root,
            requested_run_id=run_id,
        )
        self.assertTrue(state["season3"]["audition_40k_completed"])
        self.assertFalse(state["season3"]["audition_50k_completed"])

    def test_active_run_none_never_exposes_global_or_closed_progress(self) -> None:
        closed = "CLOSED_RUN"
        self.add_state(closed, True, True)
        self.write_registry(None, [self.record(closed, resume_allowed=False)])
        config = load_runtime_config(self.config_path, self.registry_path)
        self.assertIsNone(config["run_state"]["run_id"])
        self.assertFalse(config["run_state"]["season3"]["audition_40k_completed"])
        self.assertFalse(config["run_state"]["season3"]["audition_50k_completed"])

    def test_resume_rejects_a_different_run_id(self) -> None:
        self.write_registry("ACTIVE_RUN", [self.record("ACTIVE_RUN")])
        with self.assertRaisesRegex(ValueError, "ACTIVE_RUN_ID_MISMATCH"):
            resolve_run_state(
                json.loads(self.registry_path.read_text()), base_dir=self.root,
                requested_run_id="OTHER_RUN",
            )


if __name__ == "__main__":
    unittest.main()

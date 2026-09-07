import json
import tempfile
import unittest
from pathlib import Path

from offline_action_inference import analyze_episode, analyze_records, classify_unknown_click


def interaction(step, before, after, actions, classification="UNKNOWN_CLICK"):
    return {
        "kind": "demo_step",
        "step": step,
        "observation": {"state": before, "available_actions": actions},
        "human_action": {"classification": classification, "name": None},
        "after_observation": {"state": after},
    }


class OfflineActionInferenceTest(unittest.TestCase):
    def test_unique_expected_transition_is_inferred(self):
        record = interaction(7, "HOME", "PRODUCE_MENU", [
            {"name": "produce_start", "expected_next_states": ["PRODUCE_MENU"]},
            {"name": "reflection_open", "expected_next_states": ["REFLECTION"]},
            {"name": "rest", "expected_next_states": ["HOME"]},
        ])

        result = classify_unknown_click(record)

        self.assertEqual(result["status"], "INFERRED")
        self.assertEqual(result["inferred_action"], "produce_start")
        self.assertEqual(result["confidence"], 1.0)
        self.assertEqual(result["step_id"], 7)
        self.assertIn("Exactly one", result["inference_reason"])

    def test_multiple_matching_actions_are_ambiguous(self):
        record = interaction(8, "AUDITION_BATTLE", "AUDITION_BATTLE", [
            {"name": "battle_speed_cycle", "expected_next_states": ["AUDITION_BATTLE"]},
            {"name": "battle_auto_on", "expected_next_states": ["AUDITION_BATTLE"]},
        ])

        result = classify_unknown_click(record)

        self.assertEqual(result["status"], "AMBIGUOUS")
        self.assertEqual(result["matching_actions"], ["battle_speed_cycle", "battle_auto_on"])
        self.assertNotIn("inferred_action", result)

    def test_unknown_state_or_no_matching_action_is_unresolved(self):
        action = {"name": "vocal_lesson", "expected_next_states": ["VOCAL_RESULT"]}

        self.assertEqual(
            classify_unknown_click(interaction(9, "UNKNOWN", "VOCAL_RESULT", [action]))["status"],
            "UNRESOLVED",
        )
        self.assertEqual(
            classify_unknown_click(interaction(10, "PRODUCE_MENU", "UNKNOWN", [action]))["status"],
            "UNRESOLVED",
        )
        self.assertEqual(
            classify_unknown_click(interaction(11, "PRODUCE_MENU", "HOME", [action]))["status"],
            "UNRESOLVED",
        )

    def test_summary_counts_and_ranks_recoverable_transitions(self):
        home_actions = [
            {"name": "produce_start", "expected_next_states": ["PRODUCE_MENU"]},
            {"name": "rest", "expected_next_states": ["HOME"]},
        ]
        ambiguous_actions = [
            {"name": "first", "expected_next_states": ["SAME"]},
            {"name": "second", "expected_next_states": ["SAME"]},
        ]
        records = [
            interaction(1, "HOME", "PRODUCE_MENU", home_actions),
            interaction(2, "HOME", "PRODUCE_MENU", home_actions),
            interaction(3, "KNOWN", "SAME", ambiguous_actions),
            interaction(4, "UNKNOWN", "UNKNOWN", []),
            interaction(5, "HOME", "PRODUCE_MENU", home_actions, "NAMED_ACTION"),
        ]

        report = analyze_records(records)

        self.assertEqual(report["summary"], {
            "total_unknown_click": 4,
            "deterministic_recoverable_count": 2,
            "ambiguous_count": 1,
            "unresolved_count": 1,
            "top_recoverable_transitions": [{
                "before_state": "HOME",
                "after_state": "PRODUCE_MENU",
                "inferred_action": "produce_start",
                "count": 2,
            }],
        })
        self.assertEqual([item["step_id"] for item in report["inferred_actions"]], [1, 2])

    def test_episode_reader_ignores_non_interaction_records(self):
        record = interaction(12, "PRODUCE_MENU", "VOCAL_RESULT", [
            {"name": "vocal_lesson", "expected_next_states": ["VOCAL_RESULT"]},
        ])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "episode.jsonl"
            path.write_text(
                json.dumps({"kind": "session", "status": "RECORDING"}) + "\n"
                + json.dumps(record) + "\n"
                + json.dumps({"kind": "need_human_explanation", "step": 12}) + "\n",
                encoding="utf-8",
            )

            report = analyze_episode(path)

        self.assertEqual(report["summary"]["total_unknown_click"], 1)
        self.assertEqual(report["inferred_actions"][0]["inferred_action"], "vocal_lesson")


if __name__ == "__main__":
    unittest.main()

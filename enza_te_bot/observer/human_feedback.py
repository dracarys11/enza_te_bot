"""Human feedback channel: clarifications, corrections, mismatch records.

Pure data recording — no UI, no automation. A front-end (console, chat,
web panel) calls into these helpers to store what the human said/did.
"""
from __future__ import annotations

from typing import Any

from observer.trajectory_recorder import TrajectoryRecorder


class HumanFeedbackChannel:
    """Collects clarification questions and human answers for one trajectory."""

    def __init__(self, recorder: TrajectoryRecorder):
        self.recorder = recorder
        self.open_questions: list[dict[str, Any]] = []

    def ask_clarification(
        self,
        observation_id: str,
        options: list[dict[str, Any]],
        question: str = "无法确定，请确认。",
    ) -> dict[str, Any]:
        """Agent asks the human to disambiguate between candidate targets.

        v0.2: the question is persisted to clarifications.jsonl immediately.
        """
        if not options:
            raise ValueError("clarification needs at least one option")
        record = self.recorder.record_clarification(
            observation_id=observation_id,
            candidate_ids=[o.get("id", o.get("label", "")) for o in options],
            answer="",
        )
        record["question"] = question
        record["options"] = options
        record["answer"] = None
        self.open_questions.append(record)
        return record

    def answer(self, observation_id: str, chosen: str, comment: str = "") -> dict[str, Any]:
        for record in self.open_questions:
            if record["observation_id"] == observation_id and record["answer"] is None:
                record["answer"] = chosen
                record["human_comment"] = comment
                # persist the answered record (append-only log)
                self.recorder.append_clarification_record(
                    {
                        "question_id": record["question_id"],
                        "observation_id": observation_id,
                        "candidate_ids": record["candidate_ids"],
                        "answer": chosen,
                    },
                )
                return record
        raise KeyError(f"no open question for {observation_id}")

    # -- failure-sample helpers ---------------------------------------
    def record_semantic_mismatch(
        self,
        observation_id: str,
        agent_prediction: str,
        human_action_text: str,
    ) -> dict[str, Any]:
        """Agent thought the human would click X; human actually clicked Y."""
        return self.recorder.record_correction(
            observation_id=observation_id,
            agent_prediction={"target_text": agent_prediction, "type": "semantic_mismatch"},
            human_correction={"target_text": human_action_text},
            reason="semantic mismatch: predicted target differs from human action",
        )

    def record_sensor_disagreement(
        self,
        observation_id: str,
        providers: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        """e.g. Paddle found text 研修設定 while Gemini reported unknown button."""
        return self.recorder.record_correction(
            observation_id=observation_id,
            agent_prediction={"providers": providers, "type": "sensor_disagreement"},
            human_correction={},
            reason=reason,
        )

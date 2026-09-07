"""Trajectory recorder for human demonstrations — Observer v0.2.

Directory layout (per trajectory, under enza_memory/trajectories/human_demonstrations/):

  TRAJ_001/
    screenshots/001.png ...
    observations.jsonl     — canonical observation identity + visual facts
    human_actions.jsonl    — full input events performed by the human
    corrections.jsonl      — agent prediction vs human correction
    clarifications.jsonl   — agent questions + human answers

v0.2 changes:
  - no candidate_actions (action generation removed from observer)
  - canonical observation identity: observation_id / frame_id /
    sequence_number / screenshot_sha256 strongly bound
  - human action schema: action_id, observation_id, timestamp, mouse
    coordinate + coordinate_space, input_type, raw_event
  - replay integrity: fails on wrong digest, unknown observation_id,
    duplicate action_id
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TRAJECTORY_ROOT = REPO_ROOT / "enza_memory" / "trajectories" / "human_demonstrations"

VALID_COORDINATE_SPACES = frozenset({"viewport", "screenshot", "normalized"})
VALID_INPUT_TYPES = frozenset({"CLICK", "DOUBLE_CLICK", "RIGHT_CLICK", "TYPE", "KEY", "SCROLL", "MOVE"})


class ReplayIntegrityError(ValueError):
    """Raised when a trajectory fails replay integrity checks."""


def screenshot_digest(path: str | Path) -> str:
    data = Path(path).read_bytes()
    return "sha256:" + hashlib.sha256(data).hexdigest()


class TrajectoryRecorder:
    """Append-only recorder for one human demonstration trajectory."""

    OBSERVATIONS = "observations.jsonl"
    HUMAN_ACTIONS = "human_actions.jsonl"
    CORRECTIONS = "corrections.jsonl"
    CLARIFICATIONS = "clarifications.jsonl"

    def __init__(self, trajectory_id: str | None = None, root: Path | None = None):
        self.root = Path(root) if root is not None else TRAJECTORY_ROOT
        self.root.mkdir(parents=True, exist_ok=True)
        if trajectory_id is None:
            trajectory_id = self._next_id()
        self.trajectory_id = trajectory_id
        self.dir = self.root / trajectory_id
        self.screenshot_dir = self.dir / "screenshots"
        if not self.dir.exists():
            self.screenshot_dir.mkdir(parents=True)
        self._last_observation_id: str | None = None
        self._pending_prediction: dict[str, Any] | None = None

    # -- ids -----------------------------------------------------------
    def _next_id(self) -> str:
        existing = sorted(p.name for p in self.root.iterdir() if p.name.startswith("TRAJ_"))
        if not existing:
            return "TRAJ_001"
        return f"TRAJ_{int(existing[-1].split('_')[1]) + 1:03d}"

    def next_observation_id(self) -> str:
        n = len(self._read_lines(self.dir / self.OBSERVATIONS)) + 1
        return f"OBS_{n:04d}"

    def next_action_id(self) -> str:
        n = len(self._read_lines(self.dir / self.HUMAN_ACTIONS)) + 1
        return f"ACT_{n:04d}"

    # -- low level -----------------------------------------------------
    @staticmethod
    def _read_lines(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    @staticmethod
    def _append(path: Path, record: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    # -- recording -----------------------------------------------------
    def record_observation(
        self,
        observation: dict[str, Any],
        screenshot_path: str | Path,
    ) -> dict[str, Any]:
        """Persist screenshot + canonical observation record."""
        sequence_number = len(self._read_lines(self.dir / self.OBSERVATIONS)) + 1
        observation_id = observation.get("observation_id") or f"OBS_{sequence_number:04d}"
        shot_name = f"{sequence_number:03d}.png"
        target = self.screenshot_dir / shot_name
        shutil.copyfile(screenshot_path, target)
        digest = screenshot_digest(target)
        # Canonical identity: observation <-> screenshot <-> provider output.
        payload = observation.get("vision_observation") or {}
        frame_id = payload.get("capture", {}).get("frame_id", "")
        record = {
            "observation_id": observation_id,
            "frame_id": frame_id,
            "sequence_number": sequence_number,
            "screenshot_sha256": digest,
            "screenshot": f"screenshots/{shot_name}",
            "vision_source": observation.get("vision_source", "unknown"),
            "provider_metadata": observation.get("provider_metadata", {}),
            "elements": observation.get("elements", []),
            "uncertainties": observation.get("uncertainties", []),
            "vision_observation": payload,
        }
        if observation.get("candidate_actions"):
            raise ValueError(
                "Observer v0.2 forbids candidate_actions in observations"
            )
        self._append(self.dir / self.OBSERVATIONS, record)
        self._last_observation_id = observation_id
        return record

    def record_human_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Record a full human input event (v0.2 schema)."""
        required = ("action_id", "observation_id", "timestamp")
        missing = [k for k in required if not action.get(k)]
        if missing:
            raise ValueError(f"human action missing fields: {missing}")
        coordinate = action.get("mouse_coordinate")
        if coordinate is not None and (
            not isinstance(coordinate, (list, tuple))
            or len(coordinate) != 2
            or not all(isinstance(v, (int, float)) for v in coordinate)
        ):
            raise ValueError("mouse_coordinate must be [x, y] numbers")
        space = action.get("coordinate_space")
        if space is not None and space not in VALID_COORDINATE_SPACES:
            raise ValueError(f"coordinate_space must be one of {sorted(VALID_COORDINATE_SPACES)}")
        input_type = action.get("input_type")
        if input_type is not None and input_type not in VALID_INPUT_TYPES:
            raise ValueError(f"input_type must be one of {sorted(VALID_INPUT_TYPES)}")
        record = {
            "action_id": action["action_id"],
            "observation_id": action["observation_id"],
            "timestamp": action["timestamp"],
            "input_type": input_type,
            "mouse_coordinate": list(coordinate) if coordinate is not None else None,
            "coordinate_space": space,
            "target_text": action.get("target_text", ""),
            "target_element_id": action.get("target_element_id", ""),
            "human_comment": action.get("human_comment", ""),
            "raw_event": action.get("raw_event", {}),
        }
        self._append(self.dir / self.HUMAN_ACTIONS, record)
        return record

    def record_clarification(
        self,
        observation_id: str,
        candidate_ids: list[str],
        answer: str = "",
    ) -> dict[str, Any]:
        question_id = f"Q_{len(self._read_lines(self.dir / self.CLARIFICATIONS)) + 1:03d}"
        record = {
            "question_id": question_id,
            "observation_id": observation_id,
            "candidate_ids": candidate_ids,
            "answer": answer,
        }
        self._append(self.dir / self.CLARIFICATIONS, record)
        return record

    def append_clarification_record(self, record: dict[str, Any]) -> None:
        """Persist an updated/answered clarification record (append-only log)."""
        self._append(self.dir / self.CLARIFICATIONS, record)

    def record_correction(
        self,
        observation_id: str,
        agent_prediction: dict[str, Any],
        human_correction: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        record = {
            "observation_id": observation_id,
            "agent_prediction": agent_prediction,
            "human_correction": human_correction,
            "reason": reason,
        }
        self._append(self.dir / self.CORRECTIONS, record)
        return record

    # -- comparison / prediction --------------------------------------
    def set_prediction(self, prediction: dict[str, Any]) -> None:
        """Store the agent's prediction of what the human will do next."""
        self._pending_prediction = prediction

    def compare_transition(
        self,
        previous: dict[str, Any],
        human_action: dict[str, Any],
        current: dict[str, Any],
    ) -> dict[str, Any]:
        """Compare previous observation + human action vs new observation."""
        def element_keys(obs: dict[str, Any]) -> set[str]:
            return {e.get("text", e.get("id", "")) for e in obs.get("elements", [])}

        prev_elements, curr_elements = element_keys(previous), element_keys(current)
        prediction = self._pending_prediction
        self._pending_prediction = None
        predicted_texts = {p.get("target_text", "") for p in (prediction or {}).get("candidates", [])}
        actual_text = human_action.get("target_text", "")
        return {
            "observation_id": current["observation_id"],
            "previous_observation_id": previous["observation_id"],
            "human_action": human_action,
            "expected_changes": sorted(prev_elements - curr_elements),
            "actual_changes": sorted(curr_elements - prev_elements),
            "matches_prediction": (
                prediction is not None and actual_text in predicted_texts
            ),
            "prediction_was_made": prediction is not None,
        }

    # -- replay with integrity checks ----------------------------------
    def replay(self) -> list[dict[str, Any]]:
        """Replay trajectory as observation→action pairs with integrity checks.

        Fails (ReplayIntegrityError) on:
          1. wrong screenshot digest
          2. human action referencing a nonexistent observation
          3. duplicate action_id
        """
        observations = self._read_lines(self.dir / self.OBSERVATIONS)
        actions = self._read_lines(self.dir / self.HUMAN_ACTIONS)
        obs_by_id: dict[str, dict[str, Any]] = {}
        for obs in observations:
            if obs["observation_id"] in obs_by_id:
                raise ReplayIntegrityError(
                    f"duplicate observation_id {obs['observation_id']}"
                )
            obs_by_id[obs["observation_id"]] = obs
        seen_action_ids: set[str] = set()
        actions_by_obs: dict[str, dict[str, Any]] = {}
        for action in actions:
            if action["action_id"] in seen_action_ids:
                raise ReplayIntegrityError(f"duplicate action_id {action['action_id']}")
            seen_action_ids.add(action["action_id"])
            if action["observation_id"] not in obs_by_id:
                raise ReplayIntegrityError(
                    f"human action {action['action_id']} references unknown "
                    f"observation {action['observation_id']}"
                )
            actions_by_obs.setdefault(action["observation_id"], action)
        frames = []
        for obs in observations:
            shot = self.dir / obs["screenshot"]
            if not shot.exists():
                raise ReplayIntegrityError(
                    f"missing screenshot for {obs['observation_id']}"
                )
            digest = screenshot_digest(shot)
            if digest != obs["screenshot_sha256"]:
                raise ReplayIntegrityError(
                    f"screenshot digest mismatch for {obs['observation_id']}: "
                    f"expected {obs['screenshot_sha256']}, got {digest}"
                )
            frames.append(
                {
                    "observation": obs,
                    "human_action": actions_by_obs.get(obs["observation_id"]),
                }
            )
        return frames

    def clarifications(self) -> list[dict[str, Any]]:
        return self._read_lines(self.dir / self.CLARIFICATIONS)

    def corrections(self) -> list[dict[str, Any]]:
        return self._read_lines(self.dir / self.CORRECTIONS)

    def human_actions(self) -> list[dict[str, Any]]:
        return self._read_lines(self.dir / self.HUMAN_ACTIONS)

"""Vision adapter: screenshot path -> VisionObservation v0.1.

Connects ZCode screenshot capture to the external Vision Analyzer. This
module owns ONLY the connection and contract enforcement:

- input: a screenshot file path (plus an injected analyzer callable that
  stands in for the external vision service)
- output: a contract-validated VisionObservation (vision_observation_schema)

The adapter itself produces NO semantics: no semantic_state, no action, no
recommendation, no next_step, no click coordinates, no game progress. Any
such field coming back from the analyzer is rejected by the contract
validation, never cleaned up or passed through.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from vision_observation_schema import VisionContractError, VisionObservation

# External analyzer: takes a screenshot path, returns a raw JSON dict.
# It is expected to already target contract v0.1; anything it returns is
# validated before it reaches the agent.
VisionAnalyzerFn = Callable[[str], dict[str, Any]]


class ExternalAnalyzer(Protocol):
    def __call__(self, screenshot_path: str) -> dict[str, Any]: ...


class VisionAdapterError(ValueError):
    """Screenshot input or analyzer response could not be turned into an observation."""


@dataclass(frozen=True)
class VisionAdapter:
    analyzer: ExternalAnalyzer

    def analyze_screenshot(self, screenshot_path: str) -> VisionObservation:
        """Return a contract-validated VisionObservation for one screenshot."""
        if not isinstance(screenshot_path, str) or not screenshot_path.strip():
            raise VisionAdapterError("screenshot_path must be a non-empty string")
        if not os.path.isfile(screenshot_path):
            raise VisionAdapterError(f"screenshot not found: {screenshot_path}")

        raw = self.analyzer(screenshot_path)
        if not isinstance(raw, dict):
            raise VisionAdapterError("analyzer must return a JSON object")

        # The observation id and capture block may be filled by the analyzer
        # or defaulted from the file; both paths produce the same guarantees.
        payload = dict(raw)
        payload.setdefault("observation_id", self._default_observation_id(screenshot_path))
        capture = dict(payload.get("capture") or {})
        capture.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        capture.setdefault("frame_id", os.path.basename(screenshot_path))
        capture.setdefault("screenshot_digest", self._digest(screenshot_path))
        payload["capture"] = capture

        try:
            return VisionObservation.from_payload(payload)
        except VisionContractError as error:
            raise VisionAdapterError(
                f"analyzer response violates VisionObservation contract: {error}"
            ) from error

    @staticmethod
    def _digest(screenshot_path: str) -> str:
        digest = hashlib.sha256()
        with open(screenshot_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"

    @staticmethod
    def _default_observation_id(screenshot_path: str) -> str:
        return "VOBS_" + os.path.splitext(os.path.basename(screenshot_path))[0]

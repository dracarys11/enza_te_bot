"""Gemini visual-extraction adapter.

Prompt and extraction rules remain owned by skills/gemini_vision/SKILL.md.
This adapter only injects the extractor and enforces VisionObservation v0.1.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from vision_adapter import ExternalAnalyzer, VisionAdapter

from .base import VisionAgent


GEMINI_VISION_SKILL_CONTRACT = (
    Path(__file__).resolve().parents[1] / "skills" / "gemini_vision" / "SKILL.md"
)


@dataclass(frozen=True)
class GeminiVisionAdapter(VisionAgent):
    """Adapt an injected Gemini skill runner to VisionObservation JSON."""

    extractor: ExternalAnalyzer

    def observe(self, screenshot_path: str) -> dict[str, Any]:
        observation = VisionAdapter(self.extractor).analyze_screenshot(screenshot_path)
        payload = asdict(observation)
        if payload.get("visual_changes") is None:
            payload.pop("visual_changes", None)
        return payload


__all__ = ["GEMINI_VISION_SKILL_CONTRACT", "GeminiVisionAdapter"]

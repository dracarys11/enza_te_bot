"""Interface for screenshot-to-VisionObservation providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class VisionAgent(ABC):
    """A visual-facts provider with no decision or execution responsibility."""

    @abstractmethod
    def observe(self, screenshot_path: str) -> dict[str, Any]:
        """Return contract-valid VisionObservation v0.1 JSON."""
        raise NotImplementedError


__all__ = ["VisionAgent"]

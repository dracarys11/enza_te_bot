"""Model-agnostic visual-evidence agent interfaces."""

from .base import VisionAgent
from .agy_vision_bridge import (
    AgyRunnerRequest,
    AgyRunnerResult,
    AgyVisionBridge,
    AgyVisionConfig,
    AgyVisionUnknown,
    FakeAgyRunner,
    GateEvidence,
    VisionRequestResult,
    evaluate_agy_vision_bridge_gate,
    make_gate_evidence,
    vision_request,
)
from .artifact_harness import VisionArtifactHarness, VisionArtifactRoutingError
from .gemini_adapter import GeminiVisionAdapter
from .agy_cli_runner import RealAgyCliRunner, build_agy_cli_runner

__all__ = [
    "VisionAgent",
    "AgyRunnerRequest",
    "AgyRunnerResult",
    "AgyVisionBridge",
    "AgyVisionConfig",
    "AgyVisionUnknown",
    "FakeAgyRunner",
    "GateEvidence",
    "VisionRequestResult",
    "evaluate_agy_vision_bridge_gate",
    "make_gate_evidence",
    "vision_request",
    "VisionArtifactHarness",
    "VisionArtifactRoutingError",
    "GeminiVisionAdapter",
    "RealAgyCliRunner",
    "build_agy_cli_runner",
]

"""State names and immutable detection result types."""
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class State(str, Enum):
    HOME = "HOME"
    PRODUCE_MENU = "PRODUCE_MENU"
    VOCAL_RESULT = "VOCAL_RESULT"
    SUPPORT_EVENT = "SUPPORT_EVENT"
    STORY_EVENT = "STORY_EVENT"
    MORNING_EVENT = "MORNING_EVENT"
    MORNING_DIALOGUE = "MORNING_DIALOGUE"
    MORNING_CHOICE = "MORNING_CHOICE"
    TE_START = "TE_START"
    CONFIRM = "CONFIRM"
    RESULT = "RESULT"
    LOADING = "LOADING"
    ERROR_POPUP = "ERROR_POPUP"
    UNKNOWN = "UNKNOWN"


class StateLabel(str):
    """Config-defined label retaining the legacy `.value` convenience."""
    @property
    def value(self) -> str:
        return str(self)


@dataclass(frozen=True)
class Detection:
    # State labels come from config so teaching can add a human-named state
    # without requiring a source-code enum edit or a restart.
    state: StateLabel | str
    confidence: float = 0.0
    template: Optional[str] = None

    def __post_init__(self) -> None:
        raw = self.state.value if isinstance(self.state, State) else str(self.state)
        object.__setattr__(self, "state", StateLabel(raw))

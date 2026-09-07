"""Append-only shadow prediction logging."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Any


class ShadowPredictionLogger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, prediction: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(dict(prediction), ensure_ascii=False, sort_keys=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(encoded + "\n")

"""Resolve optional, repository-external data fixtures.

Large runtime captures are intentionally not versioned.  Local checkouts keep the
historical layout under ``enza_memory`` by default, while CI and fresh clones can
point at the same directory contents with ``ENZA_DATA_ROOT``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path


ENVIRONMENT_VARIABLE = "ENZA_DATA_ROOT"
MODEL_ROOT_ENVIRONMENT_VARIABLE = "ENZA_MODEL_ROOT"
HF_HUB_OFFLINE_ENVIRONMENT_VARIABLE = "HF_HUB_OFFLINE"
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_ROOT = REPOSITORY_ROOT / "enza_memory"


class MissingDataAssetError(FileNotFoundError):
    """Raised when an optional large fixture is required but unavailable."""


def data_root(*, environ: Mapping[str, str] | None = None) -> Path:
    """Return the configured data root, or the repository's ``enza_memory``."""

    values = os.environ if environ is None else environ
    configured = values.get(ENVIRONMENT_VARIABLE, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_DATA_ROOT


def model_root(*, environ: Mapping[str, str] | None = None) -> Path | None:
    """Return the optional local model root configured by the environment."""

    values = os.environ if environ is None else environ
    configured = values.get(MODEL_ROOT_ENVIRONMENT_VARIABLE, "").strip()
    if not configured:
        return None
    return Path(configured).expanduser().resolve()


def resolve_model_source(model_id: str, *, environ: Mapping[str, str] | None = None) -> str:
    """Resolve a model identifier against ``ENZA_MODEL_ROOT`` when configured.

    With no override this returns the original identifier for backwards
    compatibility.  A configured model root always takes precedence over an
    absolute or repository-relative model path supplied by the caller.
    """

    root = model_root(environ=environ)
    if root is None:
        return model_id
    relative_id = Path(model_id).name if Path(model_id).is_absolute() else Path(model_id)
    return str(root / relative_id)


def hf_hub_offline(*, environ: Mapping[str, str] | None = None) -> bool:
    """Return whether Hugging Face loading must be local-only."""

    values = os.environ if environ is None else environ
    return values.get(HF_HUB_OFFLINE_ENVIRONMENT_VARIABLE, "").strip().casefold() in {
        "1", "true", "yes", "on"
    }


def resolve_fixture_path(
    *parts: str | Path,
    required: bool = True,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve a fixture below the data root and optionally require its presence."""

    relative = Path(*parts)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"fixture path must stay below the data root: {relative}")

    root = data_root(environ=environ)
    path = root / relative
    if required and not path.is_file():
        raise MissingDataAssetError(
            f"Required enza data fixture is missing: {path}. "
            f"Set {ENVIRONMENT_VARIABLE} to a directory containing {relative}."
        )
    return path

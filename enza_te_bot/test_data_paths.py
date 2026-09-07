from __future__ import annotations

from pathlib import Path

import pytest

from enza_memory.data_paths import (
    DEFAULT_DATA_ROOT,
    ENVIRONMENT_VARIABLE,
    HF_HUB_OFFLINE_ENVIRONMENT_VARIABLE,
    MODEL_ROOT_ENVIRONMENT_VARIABLE,
    MissingDataAssetError,
    data_root,
    hf_hub_offline,
    model_root,
    resolve_fixture_path,
    resolve_model_source,
)


def test_default_repository_fixture_path():
    relative = Path("wing_runs") / "RUN" / "screenshots" / "frame.png"

    assert data_root(environ={}) == DEFAULT_DATA_ROOT
    assert resolve_fixture_path(relative, required=False, environ={}) == DEFAULT_DATA_ROOT / relative


def test_external_data_root_fixture_path(tmp_path):
    relative = Path("wing_runs") / "RUN" / "screenshots" / "frame.png"
    fixture = tmp_path / relative
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(b"fixture")

    assert resolve_fixture_path(relative, environ={ENVIRONMENT_VARIABLE: str(tmp_path)}) == fixture


def test_missing_fixture_error_explains_external_data_root(tmp_path):
    relative = Path("wing_runs") / "MISSING" / "screenshots" / "frame.png"

    with pytest.raises(MissingDataAssetError) as captured:
        resolve_fixture_path(relative, environ={ENVIRONMENT_VARIABLE: str(tmp_path)})

    message = str(captured.value)
    assert str(tmp_path / relative) in message
    assert ENVIRONMENT_VARIABLE in message


def test_model_root_environment_overrides_default_model_source(tmp_path):
    configured = tmp_path / "models"

    assert model_root(environ={MODEL_ROOT_ENVIRONMENT_VARIABLE: str(configured)}) == configured
    assert resolve_model_source(
        "google/siglip-base-patch16-224",
        environ={MODEL_ROOT_ENVIRONMENT_VARIABLE: str(configured)},
    ) == str(configured / "google/siglip-base-patch16-224")


def test_hf_hub_offline_environment_is_opt_in():
    assert hf_hub_offline(environ={}) is False
    assert hf_hub_offline(environ={HF_HUB_OFFLINE_ENVIRONMENT_VARIABLE: "true"}) is True
    assert hf_hub_offline(environ={HF_HUB_OFFLINE_ENVIRONMENT_VARIABLE: "0"}) is False

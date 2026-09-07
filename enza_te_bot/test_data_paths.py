from __future__ import annotations

from pathlib import Path

import pytest

from enza_memory.data_paths import (
    DEFAULT_DATA_ROOT,
    ENVIRONMENT_VARIABLE,
    MissingDataAssetError,
    data_root,
    resolve_fixture_path,
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

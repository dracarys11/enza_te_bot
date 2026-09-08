from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from tools.run_vlm_benchmark import (
    LocalQwenVLM,
    _coerce_observation_payload,
    check_environment,
    evaluate_records,
    normalize_prediction,
    run_benchmark,
    sha256_file,
)


class _FakeInputs(dict):
    def to(self, device: str) -> "_FakeInputs":
        return self


class _FakeProcessor:
    def apply_chat_template(self, messages, *, tokenize: bool, add_generation_prompt: bool) -> str:
        content = messages[0]["content"]
        assert {item["type"] for item in content} == {"image", "text"}
        assert tokenize is False
        assert add_generation_prompt is True
        return "formatted multimodal prompt"

    def __call__(self, *, text, images, padding, return_tensors):
        assert text == ["formatted multimodal prompt"]
        assert len(images) == 1
        assert padding is True
        assert return_tensors == "pt"
        return _FakeInputs(input_ids=[[1, 2]])

    def batch_decode(self, output, *, skip_special_tokens):
        assert output == [[3]]
        assert skip_special_tokens is True
        return [json.dumps({
            "observation": {
                "state": "MENU",
                "phase": "UNKNOWN",
                "visible_controls": ["START"],
                "layout_family": "MAIN_MENU",
            },
            "confidence": 0.8,
            "vlm_status": "OBSERVED",
        })]


class _FakeModel:
    device = "cpu"

    def generate(self, **inputs):
        assert inputs["input_ids"] == [[1, 2]]
        return [[1, 2, 3]]


class _FakeTorch:
    class _NoGrad:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def no_grad(self):
        return self._NoGrad()


def test_unknown_mode_is_observation_only(tmp_path: Path) -> None:
    image = tmp_path / "frame.png"
    image.write_bytes(b"offline")
    source = tmp_path / "inputs.jsonl"
    source.write_text(json.dumps({"image": str(image)}) + "\n", encoding="utf-8")
    result = run_benchmark(source, tmp_path / "output", tmp_path)
    assert result["inference_started"] is False
    assert result["statuses"] == {"UNKNOWN": 1}


def test_forbidden_fields_are_rejected() -> None:
    try:
        normalize_prediction({"observation": {}, "action_allowed": False})
    except ValueError as error:
        assert "forbidden" in str(error)
    else:
        raise AssertionError("forbidden field was accepted")


def test_digest_and_confidence_contract() -> None:
    assert len(sha256_file(Path(__file__))) == 64
    with_unknown = [{"image": "x", "observation": {"state": "UNKNOWN"}, "vlm_status": "UNKNOWN"}]
    assert evaluate_records(with_unknown)["unknown_handling"] == 1.0


def test_environment_does_not_load_model(tmp_path: Path) -> None:
    env = check_environment(tmp_path / "missing-model")
    assert env["model_path_exists"] is False
    assert env["inference_started"] is False


def test_qwen_adapter_one_image_smoke(tmp_path: Path) -> None:
    from PIL import Image

    image = tmp_path / "frame.png"
    Image.new("RGB", (2, 2), color="black").save(image)
    prediction = LocalQwenVLM(
        "fake-local-model",
        processor=_FakeProcessor(),
        model=_FakeModel(),
        torch_module=_FakeTorch(),
    )(image)
    assert prediction["vlm_status"] == "OBSERVED"
    assert prediction["observation"]["state"] == "MENU"
    assert set(prediction) == {"observation", "confidence", "vlm_status"}


def test_qwen_loader_uses_transformers_516_official_class(monkeypatch) -> None:
    calls = {}

    class FakeProcessorLoader:
        @staticmethod
        def from_pretrained(model_name, **kwargs):
            calls["processor"] = (model_name, kwargs)
            return object()

    class FakeQwenLoader:
        @staticmethod
        def from_pretrained(model_name, **kwargs):
            calls["model"] = (model_name, kwargs)
            return object()

    fake_transformers = types.ModuleType("transformers")
    fake_transformers.AutoProcessor = FakeProcessorLoader
    fake_transformers.Qwen2_5_VLForConditionalGeneration = FakeQwenLoader
    fake_torch = types.ModuleType("torch")
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    LocalQwenVLM("/models/Qwen2.5-VL-7B-Instruct")

    assert calls["processor"] == ("/models/Qwen2.5-VL-7B-Instruct", {"local_files_only": True})
    assert calls["model"] == (
        "/models/Qwen2.5-VL-7B-Instruct",
        {"torch_dtype": "auto", "device_map": "auto", "local_files_only": True},
    )


def test_qwen_flat_observation_is_nested_without_authority_fields() -> None:
    prediction = _coerce_observation_payload({
        "state": "UNKNOWN",
        "phase": "UNKNOWN",
        "visible_controls": ["START"],
        "layout_family": "UNKNOWN",
        "confidence": 0.5,
        "vlm_status": "OBSERVED",
    })
    assert prediction["observation"]["state"] == "UNKNOWN"
    assert prediction["confidence"] == 0.5
    assert "authority_type" not in prediction


def test_jsonl_output_is_a_file_not_a_directory(tmp_path: Path) -> None:
    image = tmp_path / "frame.png"
    image.write_bytes(b"offline")
    source = tmp_path / "inputs.jsonl"
    source.write_text(json.dumps({"image": str(image)}) + "\n", encoding="utf-8")
    output = tmp_path / "qwen_predictions.jsonl"
    result = run_benchmark(source, output, tmp_path)
    assert output.is_file()
    assert not output.is_dir()
    assert result["output"] == str(output)
    assert (tmp_path / "qwen_predictions.scores.json").is_file()

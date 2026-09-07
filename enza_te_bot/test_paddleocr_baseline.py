import json
import io
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from paddleocr_baseline import run


class PaddleOcrBaselineTests(unittest.TestCase):
    def test_json_output_exists_and_is_raw_only(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "paddle_raw.json"
            result = run(output_path=output)
            self.assertTrue(output.is_file())
            loaded = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(loaded["method"], "PaddleOCR")
            self.assertIn("text_regions", loaded)
            self.assertNotIn("state", loaded)
            self.assertNotIn("action", loaded)
            self.assertEqual(result, loaded)

    def test_successful_paddleocr_3_result_is_raw_json(self):
        class FakeResult:
            json = {"rec_texts": ["ホーム"], "rec_scores": [0.9876],
                    "rec_boxes": [[10, 20, 110, 50]]}

        class FakeOCR:
            instances = []

            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.instances.append(self)

            def predict(self, _path):
                return [FakeResult()]

        fake_module = types.SimpleNamespace(PaddleOCR=FakeOCR)
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "screen.png"
            image.write_bytes(b"fixture")
            output = Path(directory) / "raw.json"
            old = sys.modules.get("paddleocr")
            sys.modules["paddleocr"] = fake_module
            try:
                result = run(image, output)
            finally:
                if old is None:
                    sys.modules.pop("paddleocr", None)
                else:
                    sys.modules["paddleocr"] = old
            self.assertEqual(result["text_regions"][0]["text"], "ホーム")
            self.assertEqual(result["text_regions"][0]["bbox"], [10, 20, 100, 30])
            self.assertEqual(result["text_regions"][0]["confidence"], 0.9876)
            self.assertFalse(FakeOCR.instances[0].kwargs["use_doc_orientation_classify"])
            self.assertFalse(FakeOCR.instances[0].kwargs["use_doc_unwarping"])
            self.assertTrue(FakeOCR.instances[0].kwargs["use_textline_orientation"])
            self.assertNotIn("state", result)
            self.assertNotIn("action", result)

    def test_nested_paddleocr_3_result_and_polygon_fallback(self):
        class FakeResult:
            json = {"res": {"rec_texts": ["研修設定"], "rec_scores": [0.91234567],
                            "rec_polys": [[[12, 21], [112, 20], [114, 52], [10, 50]]]}}

        class FakeOCR:
            def __init__(self, **_kwargs):
                pass

            def predict(self, _path):
                return [FakeResult()]

        fake_module = types.SimpleNamespace(PaddleOCR=FakeOCR)
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "screen.png"
            image.write_bytes(b"fixture")
            output = Path(directory) / "raw.json"
            old = sys.modules.get("paddleocr")
            sys.modules["paddleocr"] = fake_module
            diagnostics = io.StringIO()
            try:
                with redirect_stderr(diagnostics):
                    result = run(image, output, debug=True)
            finally:
                if old is None:
                    sys.modules.pop("paddleocr", None)
                else:
                    sys.modules["paddleocr"] = old

            self.assertEqual(result["text_regions"], [{
                "id": "paddle_001",
                "text": "研修設定",
                "bbox": [10, 20, 104, 32],
                "confidence": 0.912346,
            }])
            self.assertIn("keys=['res']", diagnostics.getvalue())
            self.assertIn("rec_polys", diagnostics.getvalue())
            self.assertEqual(set(result), {"source_image", "method", "text_regions"})

    def test_nested_paddleocr_3_observed_rec_box_structure(self):
        class FakeResult:
            json = {"res": {
                "rec_texts": ["プロデュース選択"],
                "rec_scores": [0.999],
                "rec_boxes": [[0, 0, 231, 33]],
            }}

        class FakeOCR:
            def __init__(self, **_kwargs):
                pass

            def predict(self, _path):
                return [FakeResult()]

        fake_module = types.SimpleNamespace(PaddleOCR=FakeOCR)
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "screen.png"
            image.write_bytes(b"fixture")
            output = Path(directory) / "raw.json"
            old = sys.modules.get("paddleocr")
            sys.modules["paddleocr"] = fake_module
            try:
                result = run(image, output)
            finally:
                if old is None:
                    sys.modules.pop("paddleocr", None)
                else:
                    sys.modules["paddleocr"] = old

            self.assertEqual(result["text_regions"], [{
                "id": "paddle_001",
                "text": "プロデュース選択",
                "bbox": [0, 0, 231, 33],
                "confidence": 0.999,
            }])


if __name__ == "__main__":
    unittest.main()

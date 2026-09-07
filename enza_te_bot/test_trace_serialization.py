"""JSONL traces may contain image metadata, but never raw Pillow image objects."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from main import write_trace


class TraceSerializationTest(unittest.TestCase):
    def test_dialogue_details_with_images_are_json_safe(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            write_trace(path, {
                "kind": "dialogue_transition",
                "details": {"images": [Image.new("RGB", (12, 8))], "similarities": [0.98], "fast_path": "UNKNOWN"},
                "screenshot": "/tmp/dialogue.png",
            })
            record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["details"]["images"], [{"image_metadata": {"mode": "RGB", "size": [12, 8]}}])
        self.assertEqual(record["details"]["similarities"], [0.98])
        self.assertEqual(record["details"]["fast_path"], "UNKNOWN")
        self.assertEqual(record["screenshot"], "/tmp/dialogue.png")
        self.assertIn("timestamp", record)

    def test_unknown_runtime_object_is_rejected_explicitly(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(TypeError, "not JSON-safe"):
                write_trace(Path(directory) / "trace.jsonl", {"bad": object()})


if __name__ == "__main__":
    unittest.main()

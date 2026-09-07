import unittest

import cv2
import numpy as np
from PIL import Image

from reflection_canonical import (BoardTransform, CanonicalBoard, clockwise_ring,
                                  local_tile_evidence, point_in_roi, register_translation,
                                  rotate_to_anchor, is_configured_state)
from reflection_canonical import duplicate_target_flags


class CanonicalReflectionTests(unittest.TestCase):
    def test_axial_center_and_clockwise_ring(self):
        board = CanonicalBoard("upper_left", (0, 0, 1, 1), (10, 20), (8, 0), (4, 7), (0, 0), clockwise_ring(1))
        self.assertEqual(board.center((1, 1)), (22, 27))
        self.assertEqual(len(clockwise_ring(2)), 12)

    def test_anchor_rotation(self):
        self.assertEqual(rotate_to_anchor([(0, 0), (1, 0), (1, 1)], (1, 0)), [(1, 0), (1, 1), (0, 0)])

    def test_translation_registration(self):
        image = np.zeros((80, 80), np.uint8)
        cv2.rectangle(image, (20, 20), (50, 50), 255, 2)
        shifted = np.roll(np.roll(image, 3, axis=1), 2, axis=0)
        transform = register_translation(Image.fromarray(image), Image.fromarray(shifted))
        self.assertAlmostEqual(transform.dx, 3, delta=1.0)
        self.assertAlmostEqual(transform.dy, 2, delta=1.0)

    def test_local_evidence_and_roi_gate(self):
        image = np.zeros((120, 140), np.uint8)
        pts = np.array([[70 + 25, 60], [70 + 12, 60 + 20], [70 - 12, 60 + 20],
                        [70 - 25, 60], [70 - 12, 60 - 20], [70 + 12, 60 - 20]], np.int32)
        cv2.polylines(image, [pts], True, 255, 3)
        self.assertTrue(local_tile_evidence(Image.fromarray(image), (70, 60), (50, 40)))
        self.assertTrue(point_in_roi((0.5, 0.5), (0.2, 0.2, 0.8, 0.8)))
        self.assertFalse(point_in_roi((0.9, 0.5), (0.2, 0.2, 0.8, 0.8)))

    def test_transform_apply(self):
        self.assertEqual(BoardTransform(2, 3, 2).apply((4, 5)), (10, 13))

    def test_dynamic_reflection_label_does_not_require_enum_member(self):
        class Dynamic:
            value = "REFLECTION"
        self.assertTrue(is_configured_state(Dynamic(), "REFLECTION"))
        self.assertFalse(hasattr(__import__("states").State, "REFLECTION"))

    def test_non_reflection_and_unknown_labels_stop(self):
        self.assertFalse(is_configured_state("HOME", "REFLECTION"))
        self.assertFalse(is_configured_state("UNKNOWN", "REFLECTION"))

    def test_duplicate_flags_are_symmetric_and_space_consistent(self):
        normalized = [(0.10, 0.10), (0.40, 0.40), (0.70, 0.70), (0.10, 0.70), (0.70, 0.10), (0.50, 0.15)]
        self.assertEqual(duplicate_target_flags(normalized, (100, 80), image_size=(1000, 800), normalized=True),
                         [False] * 6)
        close = duplicate_target_flags([(0.10, 0.10), (0.11, 0.10)], (100, 80), image_size=(1000, 800), normalized=True)
        self.assertEqual(close, [True, True])
        self.assertEqual(duplicate_target_flags([(100, 100), (101, 100)], (100, 80)), [True, True])


if __name__ == "__main__":
    unittest.main()

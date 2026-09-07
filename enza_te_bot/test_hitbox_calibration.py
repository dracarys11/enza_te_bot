"""Offline tests for evidence-only hitbox calibration."""
from __future__ import annotations

import unittest

from hitbox_calibration import (
    CalibrationAttempt, CalibrationResult, CalibrationSchemaError,
    TargetCalibration, VisualBounds,
)


def calibration(result=CalibrationResult.SUCCESS, attempts=None):
    return TargetCalibration(
        "next", "OBS_001", VisualBounds((0.70, 0.70, 0.90, 0.90)),
        tuple(attempts or (CalibrationAttempt((0.80, 0.80), result, "shot.png"),)),
        result, 0.8,
    )


class HitboxCalibrationTests(unittest.TestCase):
    def test_approximate_geometry_cannot_be_exact_hitbox(self) -> None:
        with self.assertRaisesRegex(CalibrationSchemaError, "exact"):
            VisualBounds((0.1, 0.1, 0.2, 0.2), "EXACT")
        data = calibration().as_dict()
        data["visual_bounds"]["precision"] = "EXACT"
        with self.assertRaisesRegex(CalibrationSchemaError, "exact"):
            TargetCalibration.from_dict(data)

    def test_failed_click_is_recorded(self) -> None:
        attempt = CalibrationAttempt((0.5, 0.5), CalibrationResult.FAILED, "after.png")
        record = calibration(CalibrationResult.FAILED, (attempt,))
        self.assertEqual(record.result, CalibrationResult.FAILED)
        self.assertEqual(record.attempted_points[0].result, CalibrationResult.FAILED)
        self.assertEqual(record.as_dict()["attempted_points"][0]["result"], "FAILED")

    def test_unknown_is_preserved(self) -> None:
        attempt = CalibrationAttempt((0.5, 0.5), CalibrationResult.UNKNOWN, "unknown.png")
        record = calibration(CalibrationResult.UNKNOWN, (attempt,))
        restored = TargetCalibration.from_dict(record.as_dict())
        self.assertEqual(restored.result, CalibrationResult.UNKNOWN)
        self.assertEqual(restored.attempted_points[0].result, CalibrationResult.UNKNOWN)

    def test_failed_result_requires_failed_attempt_evidence(self) -> None:
        with self.assertRaisesRegex(CalibrationSchemaError, "failed click"):
            calibration(CalibrationResult.FAILED, (
                CalibrationAttempt((0.5, 0.5), CalibrationResult.UNKNOWN),
            ))

    def test_no_execution_or_click_dependency(self) -> None:
        record = calibration()
        self.assertFalse(record.as_dict()["authorizes_exact_hitbox"])
        self.assertFalse(hasattr(record, "execute"))


if __name__ == "__main__":
    unittest.main()

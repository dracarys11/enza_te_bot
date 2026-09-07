"""Offline tests for the observation-only ZCode adapter."""
from __future__ import annotations

import unittest

from zcode_observation_provider import ZCodeObservationError, ZCodeObservationProvider


def payload(*, environment=True, classification="INFERENCE"):
    return {
        "observation_id": "OBS_ZCODE_001",
        "timestamp": "2026-09-03T06:00:00Z",
        "screenshot_reference": "screenshots/OBS_ZCODE_001.png",
        "environment": {"application": "shinycolors", "viewport": {"width": 1280, "height": 720}}
        if environment else None,
        "state": {"label": "PRODUCE_SELECTION", "classification": classification},
        "visible_elements": [],
        "facts": ["screenshot captured"],
        "inferences": [],
        "unknowns": [],
    }


class ZCodeObservationProviderTests(unittest.TestCase):
    def test_mock_zcode_observation_loads_into_artifact_shape(self) -> None:
        result = ZCodeObservationProvider(lambda: payload()).observe()
        self.assertEqual(result.artifact["schema_version"], 1)
        self.assertEqual(result.artifact["capture_provenance"]["source"], "ZCODE")
        self.assertEqual(result.screenshot_reference, "screenshots/OBS_ZCODE_001.png")

    def test_screenshot_only_payload_remains_visible_only_classification(self) -> None:
        result = ZCodeObservationProvider(lambda: payload(classification="INFERENCE")).observe()
        self.assertEqual(result.artifact["state"]["classification"], "INFERENCE")
        self.assertEqual(result.status, "VISIBLE_ONLY")
        self.assertEqual(result.artifact["provider_status"], "VISIBLE_ONLY")

    def test_missing_environment_metadata_becomes_unknown(self) -> None:
        result = ZCodeObservationProvider(lambda: payload(environment=False)).observe()
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn("ZCODE_ENVIRONMENT_METADATA_MISSING", result.artifact["unknowns"])

    def test_adapter_cannot_execute_actions(self) -> None:
        provider = ZCodeObservationProvider(lambda: payload())
        with self.assertRaisesRegex(ZCodeObservationError, "observation-only"):
            provider.execute("anything")

    def test_missing_screenshot_is_rejected(self) -> None:
        data = payload()
        data.pop("screenshot_reference")
        with self.assertRaisesRegex(ZCodeObservationError, "screenshot_reference"):
            ZCodeObservationProvider(lambda: data).observe()


if __name__ == "__main__":
    unittest.main()

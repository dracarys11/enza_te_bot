"""Offline checks for HOME ROI evidence capture geometry."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import numpy as np
from PIL import Image

from home_observation import (HomeObservation, consistently_observed,
                              capture_home_observation_roi, capture_home_week_digit_template,
                              normalized_capture_roi, parse_fan_gap_to_target,
                              parse_home_sample, parse_season, parse_weeks_remaining,
                              FreshHomeCapture, WeekLearningEvidence,
                              auto_learn_week_digit_from_progression,
                              detect_fan_target_clear, detect_stamina_adequate,
                              recognize_week_digit_template, smoke_ocr)


class HomeObservationTest(unittest.TestCase):
    def test_retina_physical_crop_maps_to_normalized_logical_window(self) -> None:
        window = {"width": 1000, "height": 500}
        scale = {"x": 2.0, "y": 2.0}
        self.assertEqual(normalized_capture_roi(200, 100, 400, 200, window, scale), [0.1, 0.1, 0.3, 0.3])

    def test_out_of_window_crop_is_rejected(self) -> None:
        window = {"width": 1000, "height": 500}
        scale = {"x": 2.0, "y": 2.0}
        with self.assertRaises(ValueError):
            normalized_capture_roi(1900, 0, 200, 100, window, scale)

    def test_real_home_ocr_strings_parse_conservatively(self) -> None:
        self.assertEqual(parse_season("Y-—AY 2"), (2, None))
        self.assertEqual(parse_weeks_remaining("6 a", [0, 99]), (6, None))
        self.assertEqual(parse_fan_gap_to_target("eo 6,721 Rh"), (6721, None))
        self.assertEqual(parse_fan_gap_to_target("Fa YAR 3.385 Rh"), (3385, None))
        self.assertEqual(parse_fan_gap_to_target("eo “4,561 Rh"), (4561, None))
        self.assertEqual(parse_fan_gap_to_target("12.345"), (12345, None))

    def test_fan_target_clear_is_explicit_semantic_evidence(self) -> None:
        config = json.loads((Path(__file__).resolve().parent / "config.json").read_text())
        parsed, reasons = parse_home_sample(
            {"season": "3", "weeks_remaining": "7", "fan_gap_to_target": "", "stamina": "adequate"},
            config, fan_target_achieved=True,
        )
        self.assertEqual(reasons, {})
        self.assertEqual(parsed.fan_gap_to_target, 0)
        self.assertTrue(parsed.fan_target_achieved)

    def test_numeric_fan_gap_remains_available_and_not_achieved(self) -> None:
        config = json.loads((Path(__file__).resolve().parent / "config.json").read_text())
        parsed, reasons = parse_home_sample(
            {"season": "3", "weeks_remaining": "7", "fan_gap_to_target": "31,225", "stamina": "adequate"}, config,
        )
        self.assertEqual(reasons, {})
        self.assertEqual(parsed.fan_gap_to_target, 31225)
        self.assertFalse(parsed.fan_target_achieved)

    def test_blank_fan_gap_without_clear_remains_unreadable(self) -> None:
        config = json.loads((Path(__file__).resolve().parent / "config.json").read_text())
        parsed, reasons = parse_home_sample(
            {"season": "3", "weeks_remaining": "7", "fan_gap_to_target": "", "stamina": "adequate"}, config,
        )
        self.assertIsNone(parsed)
        self.assertIn("fan_gap_to_target", reasons)

    def test_real_season_three_clear_home_screenshot(self) -> None:
        base = Path(__file__).resolve().parent
        path = base / "logs" / "20260831_214046_696966_HOME_OBSERVATION_SAMPLE_1.png"
        if not path.exists():
            self.skipTest("real achieved HOME fixture not present")
        config = json.loads((base / "config.json").read_text())
        spec = config["perception"]["home_observation"]["fan_gap_to_target"]
        image = Image.open(path)
        left, top, right, bottom = spec["roi"]
        crop = image.crop((round(left * image.width), round(top * image.height),
                           round(right * image.width), round(bottom * image.height)))
        evidence = detect_fan_target_clear(crop, spec["clear_marker"])
        self.assertTrue(evidence["visible"], evidence)

    def test_multiple_or_malformed_numbers_are_rejected(self) -> None:
        self.assertIsNotNone(parse_season("season 2 week 6")[1])
        self.assertIsNotNone(parse_weeks_remaining("6 / 7", [0, 99])[1])
        self.assertIsNotNone(parse_fan_gap_to_target("6,72")[1])
        self.assertIsNotNone(parse_fan_gap_to_target("3.38")[1])
        self.assertIsNotNone(parse_fan_gap_to_target("3.3.85")[1])
        self.assertIsNotNone(parse_fan_gap_to_target("3 385")[1])
        self.assertIsNotNone(parse_fan_gap_to_target("3,385 4,561")[1])
        self.assertIsNotNone(parse_season("season 5")[1])

    def test_observation_requires_two_matching_complete_samples(self) -> None:
        first = HomeObservation(2, 6, 6721)
        self.assertIsNone(consistently_observed([first]))
        self.assertIsNone(consistently_observed([first, HomeObservation(2, 5, 6721)]))
        self.assertEqual(consistently_observed([first, HomeObservation(2, 5, 6721), first]), first)

    def test_single_field_reteach_preserves_other_home_roi_values(self) -> None:
        config = {
            "capture_scale": {"x": 2.0, "y": 2.0},
            "game_window": {"left": 1},
            "perception": {"home_observation": {
                "season": {"roi": [0.1, 0.1, 0.2, 0.2], "range": [1, 4]},
                "weeks_remaining": {"roi": [0.3, 0.1, 0.4, 0.2], "range": [0, 99]},
                "fan_gap_to_target": {"roi": [0.5, 0.1, 0.6, 0.2]},
                "stamina": {"roi": [0.7, 0.1, 0.8, 0.2]},
            }},
        }
        before = deepcopy(config["perception"]["home_observation"])
        image = Image.new("RGB", (2000, 1000))
        selection = ((700, 100, 100, 100), (350, 50, 50, 50), (2000, 1000), (1000, 500), 0.5, (1500, 1000))
        with patch("home_observation.select_scaled_roi", return_value=selection), \
             patch("home_observation.backup_and_write_config", return_value="backup.json") as write:
            result = capture_home_observation_roi(image, {"width": 1000, "height": 500}, config, "weeks_remaining")
        self.assertEqual(result["roi"], [0.35, 0.1, 0.4, 0.2])
        self.assertEqual(config["perception"]["home_observation"]["season"], before["season"])
        self.assertEqual(config["perception"]["home_observation"]["fan_gap_to_target"], before["fan_gap_to_target"])
        self.assertEqual(config["perception"]["home_observation"]["stamina"], before["stamina"])
        self.assertEqual(config["perception"]["home_observation"]["weeks_remaining"]["range"], before["weeks_remaining"]["range"])
        self.assertNotIn("capture_scale", config)
        self.assertIsNone(config["game_window"])
        write.assert_called_once()

    def test_detect_stamina_adequate_full_bar(self) -> None:
        # Synthetic green bar across 100% of the crop
        pixels = np.zeros((20, 100, 3), dtype=np.uint8)
        pixels[:, :] = [50, 200, 50]  # bright green
        crop = Image.fromarray(pixels)
        evidence = detect_stamina_adequate(crop)
        self.assertIs(evidence["adequate"], True)
        self.assertEqual(evidence["source"], "home_stamina_adequate_visual_marker")

    def test_detect_stamina_adequate_low_bar(self) -> None:
        # Synthetic green bar across only left 25% of the crop (< 50%)
        pixels = np.zeros((20, 100, 3), dtype=np.uint8)
        pixels[:, :25] = [50, 200, 50]  # green left 25%
        crop = Image.fromarray(pixels)
        evidence = detect_stamina_adequate(crop)
        self.assertIs(evidence["adequate"], False)

    def test_detect_stamina_adequate_blank_crop_fails_closed(self) -> None:
        # Pure dark / blank background without stamina fill
        pixels = np.zeros((20, 100, 3), dtype=np.uint8)
        crop = Image.fromarray(pixels)
        evidence = detect_stamina_adequate(crop)
        self.assertIsNone(evidence["adequate"])
        self.assertIn("blank/unreadable", evidence["reason"])

    def test_smoke_ocr_stamina(self) -> None:
        pixels = np.zeros((20, 100, 3), dtype=np.uint8)
        pixels[:, :] = [50, 200, 50]
        image = Image.fromarray(pixels)
        raw, diagnostics = smoke_ocr(image, {"stamina": [0.0, 0.0, 1.0, 1.0]})
        self.assertEqual(raw["stamina"], "adequate")
        self.assertEqual(diagnostics["stamina"]["method"], "home_stamina_adequate_visual_marker")
        self.assertIs(diagnostics["stamina"]["stamina"]["adequate"], True)

    def test_parse_home_sample_with_stamina(self) -> None:
        config = {
            "perception": {"home_observation": {
                "season": {"range": [1, 4]},
                "weeks_remaining": {"range": [0, 99]},
                "fan_gap_to_target": {},
                "stamina": {},
            }},
        }
        # Valid stamina adequate
        parsed, reasons = parse_home_sample(
            {"season": "3", "weeks_remaining": "7", "fan_gap_to_target": "0"},
            config, fan_target_achieved=True, stamina_adequate=True,
        )
        self.assertEqual(reasons, {})
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.stamina_adequate)

        # Valid stamina low
        parsed_low, reasons_low = parse_home_sample(
            {"season": "3", "weeks_remaining": "7", "fan_gap_to_target": "0"},
            config, fan_target_achieved=True, stamina_adequate=False,
        )
        self.assertEqual(reasons_low, {})
        self.assertFalse(parsed_low.stamina_adequate)

        # Ambiguous / unreadable stamina fails closed
        parsed_none, reasons_none = parse_home_sample(
            {"season": "3", "weeks_remaining": "7", "fan_gap_to_target": "0"},
            config, fan_target_achieved=True, stamina_adequate=None,
        )
        self.assertIsNone(parsed_none)
        self.assertIn("stamina", reasons_none)

    def test_season_and_fan_gap_keep_generic_ocr_behavior(self) -> None:
        image = Image.new("RGB", (100, 100))
        rois = {"season": [0.0, 0.0, 1.0, 1.0], "fan_gap_to_target": [0.0, 0.0, 1.0, 1.0]}
        with patch("home_observation._ocr_text", side_effect=["Y-—AY 2", "eo 6,721 Rh"]) as ocr:
            raw, diagnostics = smoke_ocr(image, rois)
        self.assertEqual(raw, {"season": "Y-—AY 2", "fan_gap_to_target": "eo 6,721 Rh"})
        self.assertIsNone(diagnostics["season"]["digit_raw"])
        self.assertIsNone(diagnostics["fan_gap_to_target"]["digit_raw"])
        self.assertEqual([call.args[1] for call in ocr.call_args_list], ["--psm 7", "--psm 7"])

    @staticmethod
    def _digit_image(seed: int) -> Image.Image:
        pixels = np.random.default_rng(seed).integers(0, 256, size=(40, 30), dtype=np.uint8)
        return Image.fromarray(pixels)

    @staticmethod
    def _matching() -> dict:
        return {"directory": "templates/home_weeks_digits", "confidence_threshold": 0.90,
                "min_margin": 0.05, "digits": {"4": "4.png"}}

    def test_exact_taught_week_digit_template_is_recognized(self) -> None:
        image = self._digit_image(4)
        with TemporaryDirectory() as temporary, patch("home_observation.BASE_DIR", Path(temporary)):
            directory = Path(temporary) / "templates" / "home_weeks_digits"
            directory.mkdir(parents=True)
            image.save(directory / "4.png")
            result = recognize_week_digit_template(image, self._matching())
        self.assertEqual(result["selected_raw"], "4")
        self.assertGreater(result["top_score"], 0.90)

    def test_low_confidence_week_template_is_unreadable(self) -> None:
        current = self._digit_image(4)
        with TemporaryDirectory() as temporary, patch("home_observation.BASE_DIR", Path(temporary)):
            directory = Path(temporary) / "templates" / "home_weeks_digits"
            directory.mkdir(parents=True)
            self._digit_image(5).save(directory / "4.png")
            result = recognize_week_digit_template(current, self._matching())
        self.assertEqual(result["selected_raw"], "")
        self.assertEqual(result["recognition_error"], "low confidence or ambiguous top digit")

    def test_ambiguous_week_template_scores_are_unreadable(self) -> None:
        image = self._digit_image(4)
        matching = self._matching()
        matching["digits"] = {"4": "4.png", "5": "5.png"}
        with TemporaryDirectory() as temporary, patch("home_observation.BASE_DIR", Path(temporary)):
            directory = Path(temporary) / "templates" / "home_weeks_digits"
            directory.mkdir(parents=True)
            image.save(directory / "4.png")
            image.save(directory / "5.png")
            result = recognize_week_digit_template(image, matching)
        self.assertEqual(result["selected_raw"], "")
        self.assertEqual(result["margin"], 0.0)

    def test_missing_week_digit_template_is_unreadable(self) -> None:
        with TemporaryDirectory() as temporary, patch("home_observation.BASE_DIR", Path(temporary)):
            result = recognize_week_digit_template(self._digit_image(4), self._matching())
        self.assertEqual(result["selected_raw"], "")
        self.assertEqual(result["recognition_error"], "missing or unreadable configured digit templates")

    def test_teaching_week_digit_captures_existing_roi_and_registers_it_safely(self) -> None:
        config = {
            "capture_scale": {"x": 2.0, "y": 2.0}, "game_window": {"left": 1},
            "perception": {"home_observation": {
                "season": {"roi": [0.1, 0.1, 0.2, 0.2], "range": [1, 4]},
                "weeks_remaining": {"roi": [0.3, 0.1, 0.4, 0.2], "range": [0, 99]},
                "fan_gap_to_target": {"roi": [0.5, 0.1, 0.6, 0.2]},
                "stamina": {"roi": [0.7, 0.1, 0.8, 0.2]},
            }},
        }
        image = self._digit_image(4).resize((1000, 500))
        with TemporaryDirectory() as temporary, \
             patch("home_observation.WEEKS_TEMPLATE_DIR", Path(temporary) / "home_weeks_digits"), \
             patch("home_observation.backup_and_write_config", return_value="backup.json") as write:
            result = capture_home_week_digit_template(image, config, "4")
            self.assertTrue(Path(result["template"]).is_file())
        self.assertEqual(result["roi"], [0.3, 0.1, 0.4, 0.2])
        self.assertEqual(config["perception"]["home_observation"]["weeks_remaining"]["template_matching"]["digits"], {"4": "4.png"})
        self.assertNotIn("capture_scale", config)
        self.assertIsNone(config["game_window"])
        write.assert_called_once()

    def test_template_weeks_path_leaves_season_and_fan_gap_on_generic_ocr(self) -> None:
        image = self._digit_image(4)
        rois = {"season": [0.0, 0.0, 1.0, 1.0], "weeks_remaining": [0.0, 0.0, 1.0, 1.0],
                "fan_gap_to_target": [0.0, 0.0, 1.0, 1.0]}
        with TemporaryDirectory() as temporary, patch("home_observation.BASE_DIR", Path(temporary)):
            directory = Path(temporary) / "templates" / "home_weeks_digits"
            directory.mkdir(parents=True)
            image.save(directory / "4.png")
            with patch("home_observation._ocr_text", side_effect=["Y-—AY 2", "eo 6,721 Rh"]) as ocr:
                raw, diagnostics = smoke_ocr(image, rois, weeks_template_matching=self._matching())
        self.assertEqual(raw, {"season": "Y-—AY 2", "weeks_remaining": "4", "fan_gap_to_target": "eo 6,721 Rh"})
        self.assertEqual(diagnostics["weeks_remaining"]["method"], "opencv_digit_template")
        self.assertEqual([call.args[1] for call in ocr.call_args_list], ["--psm 7", "--psm 7"])

    def _learning_config(self) -> dict:
        return {"capture_scale": {"x": 2.0, "y": 2.0}, "game_window": {"left": 1},
                "perception": {"home_observation": {
                    "season": {"roi": [0.0, 0.0, 0.2, 0.2], "range": [1, 4]},
                    "weeks_remaining": {"roi": [0.2, 0.2, 0.8, 0.8], "range": [0, 99],
                                        "template_matching": {"directory": "templates/home_weeks_digits",
                                                              "confidence_threshold": 0.90, "min_margin": 0.05,
                                                              "digits": {"4": "4.png"}}},
                    "fan_gap_to_target": {"roi": [0.8, 0.8, 1.0, 1.0]},
                    "stamina": {"roi": [0.0, 0.8, 0.2, 1.0]},
                }}}

    def _learning_image(self, weeks_digit_seed: int) -> Image.Image:
        image = np.zeros((100, 100), dtype=np.uint8)
        image[20:80, 20:80] = np.array(self._digit_image(weeks_digit_seed).resize((60, 60)))
        return Image.fromarray(image)

    @staticmethod
    def _learning_evidence(**changes) -> WeekLearningEvidence:
        values = {"previous_week": 4, "previous_season": 2, "action_name": "vocal_lesson",
                  "action_sent": True, "action_completed_at_home": True,
                  "consumes_one_week": True, "boundary_season": 2}
        values.update(changes)
        return WeekLearningEvidence(**values)

    def _write_existing_four(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self._learning_image(4).crop((20, 20, 80, 80)).save(directory / "4.png")

    def test_verified_one_week_vocal_transaction_teaches_three(self) -> None:
        config = self._learning_config()
        current = self._learning_image(3)
        with TemporaryDirectory() as temporary, \
             patch("home_observation.BASE_DIR", Path(temporary)), \
             patch("home_observation.WEEKS_TEMPLATE_DIR", Path(temporary) / "templates" / "home_weeks_digits"), \
             patch("home_observation.backup_and_write_config", return_value=Path("backup.json")) as write:
            directory = Path(temporary) / "templates" / "home_weeks_digits"
            self._write_existing_four(directory)
            fresh = lambda: FreshHomeCapture(current.copy(), "HOME", 2, "fresh.png")
            result = auto_learn_week_digit_from_progression(current, config, self._learning_evidence(), fresh)
            self.assertTrue((directory / "3.png").is_file())
        self.assertEqual(result["status"], "COMMITTED")
        self.assertEqual(config["perception"]["home_observation"]["weeks_remaining"]["template_matching"]["digits"]["3"], "3.png")
        write.assert_called_once()

    def test_action_sent_without_room_completion_does_not_auto_teach(self) -> None:
        config = self._learning_config()
        with TemporaryDirectory() as temporary, patch("home_observation.BASE_DIR", Path(temporary)), \
             patch("home_observation.WEEKS_TEMPLATE_DIR", Path(temporary) / "templates" / "home_weeks_digits"):
            result = auto_learn_week_digit_from_progression(
                self._learning_image(3), config, self._learning_evidence(action_completed_at_home=False),
                lambda: FreshHomeCapture(self._learning_image(3), "HOME", 2, "fresh.png"))
        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(result["reason"], "no_verified_week_consuming_action")

    def test_season_boundary_does_not_auto_teach(self) -> None:
        config = self._learning_config()
        with TemporaryDirectory() as temporary, patch("home_observation.BASE_DIR", Path(temporary)), \
             patch("home_observation.WEEKS_TEMPLATE_DIR", Path(temporary) / "templates" / "home_weeks_digits"):
            result = auto_learn_week_digit_from_progression(
                self._learning_image(3), config, self._learning_evidence(boundary_season=3),
                lambda: FreshHomeCapture(self._learning_image(3), "HOME", 3, "fresh.png"))
        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(result["reason"], "season_boundary_or_unreadable_boundary_season")

    def test_confident_existing_digit_blocks_auto_teach(self) -> None:
        config = self._learning_config()
        current = self._learning_image(3)
        with TemporaryDirectory() as temporary, patch("home_observation.BASE_DIR", Path(temporary)), \
             patch("home_observation.WEEKS_TEMPLATE_DIR", Path(temporary) / "templates" / "home_weeks_digits"):
            directory = Path(temporary) / "templates" / "home_weeks_digits"
            directory.mkdir(parents=True)
            current.crop((20, 20, 80, 80)).save(directory / "4.png")
            result = auto_learn_week_digit_from_progression(
                current, config, self._learning_evidence(),
                lambda: FreshHomeCapture(current.copy(), "HOME", 2, "fresh.png"))
        self.assertEqual(result["reason"], "existing_confident_digit_blocks_learning")
        self.assertEqual(result["existing_digit"], "4")

    def test_failed_fresh_verification_quarantines_candidate_without_config_change(self) -> None:
        config = self._learning_config()
        current, fresh_image = self._learning_image(3), self._learning_image(8)
        with TemporaryDirectory() as temporary, patch("home_observation.BASE_DIR", Path(temporary)), \
             patch("home_observation.WEEKS_TEMPLATE_DIR", Path(temporary) / "templates" / "home_weeks_digits"):
            directory = Path(temporary) / "templates" / "home_weeks_digits"
            self._write_existing_four(directory)
            result = auto_learn_week_digit_from_progression(
                current, config, self._learning_evidence(),
                lambda: FreshHomeCapture(fresh_image, "HOME", 2, "fresh.png"))
            self.assertTrue(Path(result["quarantine_path"]).is_file())
        self.assertEqual(result["status"], "UNREADABLE")
        self.assertNotIn("3", config["perception"]["home_observation"]["weeks_remaining"]["template_matching"]["digits"])

    def test_existing_three_template_is_never_overwritten(self) -> None:
        config = self._learning_config()
        config["perception"]["home_observation"]["weeks_remaining"]["template_matching"]["digits"]["3"] = "3.png"
        with TemporaryDirectory() as temporary, patch("home_observation.BASE_DIR", Path(temporary)), \
             patch("home_observation.WEEKS_TEMPLATE_DIR", Path(temporary) / "templates" / "home_weeks_digits"):
            result = auto_learn_week_digit_from_progression(
                self._learning_image(3), config, self._learning_evidence(),
                lambda: FreshHomeCapture(self._learning_image(3), "HOME", 2, "fresh.png"))
        self.assertEqual(result["reason"], "inferred_digit_template_already_exists")


if __name__ == "__main__":
    unittest.main()

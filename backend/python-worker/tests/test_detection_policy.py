"""Unit tests for Area detection confidence and temporal-confirmation policy."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from detection.policy import (
    DetectionPolicy,
    DetectionPolicyConfigurationError,
    DetectionThresholds,
    TemporalConfirmationWindow,
)


class DetectionPolicyTests(unittest.TestCase):
    def test_safe_defaults_are_immutable_and_apply_by_source(self) -> None:
        policy = DetectionPolicy.from_environment({})

        self.assertEqual(policy.thresholds_for("base", "person"), DetectionThresholds(0.30, 0.14))
        self.assertEqual(policy.thresholds_for("custom", "reach_stacker"), DetectionThresholds(0.45, 0.25))
        with self.assertRaises(AttributeError):
            policy.base_default.initiation = 0.99  # type: ignore[misc]
        with self.assertRaises(TypeError):
            policy.base_overrides["person"] = DetectionThresholds(0.40, 0.20)  # type: ignore[index]

    def test_json_overrides_are_per_source_and_class(self) -> None:
        policy = DetectionPolicy.from_environment(
            {
                "AREA_CLASS_THRESHOLDS_JSON": (
                    '{"base":{"person":{"initiation":0.35,"continuation":0.16}},'
                    '"custom":{"reach_stacker":{"initiation":0.50,"continuation":0.28}}}'
                )
            }
        )

        self.assertEqual(policy.thresholds_for("COCO", "person"), DetectionThresholds(0.35, 0.16))
        self.assertEqual(
            policy.thresholds_for("CUSTOM", "reach_stacker"),
            DetectionThresholds(0.50, 0.28),
        )
        self.assertEqual(policy.thresholds_for("base", "truck"), DetectionThresholds(0.30, 0.14))
        self.assertEqual(policy.thresholds_for("custom", "forklift"), DetectionThresholds(0.45, 0.25))

    def test_deployed_legacy_base_thresholds_remain_effective_until_calibrated(self) -> None:
        policy = DetectionPolicy.from_environment({
            "AREA_TRACK_INITIATION_CONFIDENCE": "0.14",
            "AREA_TRACK_CONTINUATION_CONFIDENCE": "0.08",
        })

        self.assertEqual(policy.thresholds_for("base", "truck"), DetectionThresholds(0.14, 0.08))
        self.assertTrue(policy.can_initiate("base", "truck", 0.14))
        self.assertFalse(policy.can_initiate("base", "truck", 0.139))
        self.assertTrue(policy.can_continue("base", "truck", 0.08))

    def test_per_class_calibration_may_be_lower_than_benchmark_default(self) -> None:
        policy = DetectionPolicy.from_environment({
            "AREA_CLASS_THRESHOLDS_JSON": (
                '{"base":{"truck":{"initiation":0.18,"continuation":0.09}}}'
            )
        })

        self.assertEqual(policy.thresholds_for("base", "truck"), DetectionThresholds(0.18, 0.09))

    def test_invalid_environment_configuration_is_rejected(self) -> None:
        invalid_environments = (
            {"AREA_CLASS_THRESHOLDS_JSON": "not-json"},
            {"AREA_CLASS_THRESHOLDS_JSON": "[]"},
            {"AREA_CLASS_THRESHOLDS_JSON": '{"unknown":{}}'},
            {"AREA_CLASS_THRESHOLDS_JSON": '{"base":{"person":{"initiation":1.1,"continuation":0.2}}}'},
            {"AREA_CLASS_THRESHOLDS_JSON": '{"base":{"person":{"initiation":0.35,"continuation":0.36}}}'},
            {"AREA_TRACK_INITIATION_CONFIDENCE": "not-a-number"},
            {"AREA_TRACK_CONTINUATION_CONFIDENCE": "-0.1"},
            {"AREA_TRACK_INITIATION_CONFIDENCE": "0.10", "AREA_TRACK_CONTINUATION_CONFIDENCE": "0.11"},
            {"CUSTOM_CONFIRM_HITS": "1"},
            {"CUSTOM_CONFIRM_WINDOW": "2"},
            {"CUSTOM_CONFIRM_HITS": "two"},
            {"CUSTOM_CONFIRM_WINDOW": "three"},
        )

        for environment in invalid_environments:
            with self.subTest(environment=environment):
                with self.assertRaises(DetectionPolicyConfigurationError):
                    DetectionPolicy.from_environment(environment)

    def test_low_confidence_can_continue_only_a_confirmed_track(self) -> None:
        policy = DetectionPolicy.from_environment({})

        self.assertFalse(policy.can_initiate("base", "truck", 0.29))
        self.assertTrue(policy.can_continue("base", "truck", 0.20))
        self.assertFalse(policy.can_use_observation("base", "truck", 0.20, has_confirmed_track=False))
        self.assertTrue(policy.can_use_observation("base", "truck", 0.20, has_confirmed_track=True))
        self.assertFalse(policy.can_use_observation("base", "truck", 0.13, has_confirmed_track=True))

    def test_temporal_confirmation_requires_two_hits_in_latest_three_frames(self) -> None:
        window = TemporalConfirmationWindow(required_hits=2, window_size=3)

        self.assertFalse(window.observe("reach-7", frame_index=10, matched=True))
        self.assertFalse(window.observe("reach-7", frame_index=11, matched=False))
        self.assertTrue(window.observe("reach-7", frame_index=12, matched=True))
        self.assertFalse(window.observe("other", frame_index=12, matched=True))
        self.assertFalse(window.observe("reach-7", frame_index=13, matched=False))
        self.assertFalse(window.observe("reach-7", frame_index=14, matched=False))

    def test_temporal_confirmation_rejects_non_monotonic_frame_index(self) -> None:
        window = TemporalConfirmationWindow(required_hits=2, window_size=3)
        window.observe("reach-7", frame_index=10, matched=True)

        with self.assertRaises(ValueError):
            window.observe("reach-7", frame_index=9, matched=True)


if __name__ == "__main__":
    unittest.main()

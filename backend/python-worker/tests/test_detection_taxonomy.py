"""Cross-runtime parity checks for the shared detection taxonomy."""
from __future__ import annotations

import json
import math
import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from detection.taxonomy import (
    DETECTION_TAXONOMY,
    ActiveModelInput,
    DetectionInputValidationError,
    DetectionTaxonomyValidationError,
    RegistryLabelInput,
    decode_detection_taxonomy,
    parse_active_model_input,
    parse_registry_label_input,
    resolve_label_capability,
)


class DetectionTaxonomyTests(unittest.TestCase):
    def test_unified_manifest_owns_coco_and_custom_classes_exactly(self) -> None:
        active_model = {
            "versionKey": "unified-v1",
            "runtimeMode": "UNIFIED",
            "labelMap": {"truck": "truck", "reach_stacker": "reach_stacker"},
        }
        truck = resolve_label_capability(
            {"vietnameseName": "Xe táº£i", "baseClass": "truck"},
            active_model,
        )
        missing_car = resolve_label_capability(
            {"vietnameseName": "Xe con", "baseClass": "car"},
            active_model,
        )
        self.assertEqual(truck.detection_source, "CUSTOM")
        self.assertEqual(truck.reason_code, "ACTIVE_UNIFIED_CLASS")
        self.assertEqual(truck.active_model_version, "unified-v1")
        self.assertFalse(missing_car.is_detectable)
        self.assertEqual(missing_car.reason_code, "UNIFIED_CLASS_NOT_IN_ACTIVE_MODEL")

    def test_legacy_manifest_defaults_to_supplemental_and_runtime_mode_is_strict(self) -> None:
        parsed = parse_active_model_input({
            "versionKey": "legacy-v1",
            "labelMap": {"reach": "reach_stacker"},
        })
        self.assertEqual(parsed.runtime_mode, "SUPPLEMENTAL")
        with self.assertRaises(DetectionInputValidationError):
            parse_active_model_input({
                "versionKey": "bad-v1",
                "runtimeMode": "PRIMARY",
                "labelMap": {"reach": "reach_stacker"},
            })

    def test_exact_active_manifest_repairs_legacy_xe_nang_read_routing(self) -> None:
        capability = resolve_label_capability(
            {"vietnameseName": "Xe nâng", "baseClass": "truck"},
            {"versionKey": "custom-legacy", "labelMap": {"Xe nâng": "reach stacker"}},
        )

        self.assertEqual(capability.canonical_class, "reach_stacker")
        self.assertEqual(capability.detection_source, "CUSTOM")
        self.assertTrue(capability.is_detectable)
        self.assertEqual(capability.reason_code, "ACTIVE_CUSTOM_LEGACY_LABEL")

    @classmethod
    def setUpClass(cls) -> None:
        cases_path = Path(__file__).resolve().parents[2] / "config" / "detection-taxonomy-cases.json"
        cls.fixture = json.loads(cases_path.read_text(encoding="utf-8"))
        taxonomy_path = Path(__file__).resolve().parents[2] / "config" / "detection-taxonomy.json"
        cls.raw_taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))

    def test_shared_parity_cases(self) -> None:
        self.assertEqual(self.fixture["schemaVersion"], 1)
        self.assertEqual(len(self.fixture["cases"]), 19)  # original 13, reserved-name parity, shared whitespace, U+001C edges
        for test_case in self.fixture["cases"]:
            with self.subTest(test_case["name"]):
                actual = resolve_label_capability(test_case["label"], test_case["activeModel"]).as_dict()
                self.assertEqual(actual, test_case["expected"])

    def test_sample_count_does_not_affect_runtime_capability(self) -> None:
        zero_samples = {"vietnameseName": "Xe nâng container", "baseClass": "reach_stacker", "sampleCount": 0}
        many_samples = {"vietnameseName": "Xe nâng container", "baseClass": "reach_stacker", "sampleCount": 10_000}
        active_model = {"versionKey": "custom-v1", "labelMap": {"Xe nâng container": "reach_stacker"}}
        self.assertEqual(resolve_label_capability(zero_samples, active_model), resolve_label_capability(many_samples, active_model))

    def test_capability_ignores_malformed_or_direct_sample_count(self) -> None:
        active_model = {"versionKey": "custom-v1", "labelMap": {"Xe nâng container": "reach_stacker"}}
        expected = resolve_label_capability(
            {"vietnameseName": "Xe nâng container", "baseClass": "reach_stacker"},
            active_model,
        )
        self.assertEqual(
            resolve_label_capability(
                {
                    "vietnameseName": "Xe nâng container",
                    "baseClass": "reach_stacker",
                    "sampleCount": {"malformed": True},
                    "_count": {"samples": float("nan")},
                },
                active_model,
            ),
            expected,
        )
        self.assertEqual(
            resolve_label_capability(RegistryLabelInput("Xe tải", "truck", -1), None).reason_code,
            "COCO_BASE_CLASS",
        )

    def test_malformed_input_parity_fixture(self) -> None:
        for test_case in self.fixture["malformedInputs"]:
            parser = parse_registry_label_input if test_case["target"] == "registry" else parse_active_model_input
            with self.subTest(test_case["name"]):
                with self.assertRaises(DetectionInputValidationError) as raised:
                    parser(test_case["value"])
                self.assertEqual(raised.exception.category, test_case["expectedCategory"])

    def test_direct_dataclass_inputs_are_revalidated_at_resolver_boundary(self) -> None:
        invalid_cases = (
            (
                "blank direct ActiveModelInput version",
                RegistryLabelInput("X", "reach_stacker"),
                ActiveModelInput("   ", {"X": "reach_stacker"}),
            ),
            (
                "invalid direct ActiveModelInput labelMap",
                RegistryLabelInput("X", "reach_stacker"),
                ActiveModelInput("custom-v1", {"X": "container"}),
            ),
        )
        for name, label, active_model in invalid_cases:
            with self.subTest(name):
                with self.assertRaises(DetectionInputValidationError) as raised:
                    resolve_label_capability(label, active_model)
                self.assertEqual(raised.exception.category, "INPUT_VALIDATION")

    def test_malformed_taxonomy_parity_fixture(self) -> None:
        for test_case in self.fixture["malformedTaxonomy"]:
            candidate = deepcopy(self.raw_taxonomy)
            current = candidate
            for key in test_case["path"][:-1]:
                current = current[key]
            leaf = test_case["path"][-1]
            if test_case.get("delete"):
                del current[leaf]
            else:
                current[leaf] = test_case["value"]
            with self.subTest(test_case["name"]):
                with self.assertRaises(DetectionTaxonomyValidationError) as raised:
                    decode_detection_taxonomy(candidate)
                self.assertEqual(raised.exception.category, test_case["expectedCategory"])

    def test_schema_accepts_integral_json_numbers_and_normalizes_to_int(self) -> None:
        candidate = deepcopy(self.raw_taxonomy)
        candidate["schemaVersion"] = 1.0
        candidate["cocoClasses"]["person"] = 0.0
        normalized = decode_detection_taxonomy(candidate)
        self.assertEqual(normalized["schemaVersion"], 1)
        self.assertEqual(normalized["cocoClasses"]["person"], 0)
        self.assertIsInstance(normalized["schemaVersion"], int)
        self.assertIsInstance(normalized["cocoClasses"]["person"], int)

    def test_schema_rejects_nonintegral_or_unsafe_values(self) -> None:
        for value in (True, 1.5, math.nan, math.inf, -math.inf, 9_007_199_254_740_992):
            with self.subTest(value=value):
                candidate = deepcopy(self.raw_taxonomy)
                candidate["schemaVersion"] = value
                with self.assertRaises(DetectionTaxonomyValidationError):
                    decode_detection_taxonomy(candidate)

    def test_coco_ids_reject_boolean_fractional_nonfinite_or_unsafe_values(self) -> None:
        for value in (True, 0.5, math.nan, math.inf, -math.inf, 9_007_199_254_740_992):
            with self.subTest(value=value):
                candidate = deepcopy(self.raw_taxonomy)
                candidate["cocoClasses"]["person"] = value
                with self.assertRaises(DetectionTaxonomyValidationError):
                    decode_detection_taxonomy(candidate)

    def test_sample_count_accepts_integral_json_float_and_normalizes_to_int(self) -> None:
        parsed = parse_registry_label_input({
            "vietnameseName": "Xe tải",
            "baseClass": "truck",
            "sampleCount": 0.0,
        })
        self.assertEqual(parsed.sample_count, 0)
        self.assertIsInstance(parsed.sample_count, int)

    def test_taxonomy_is_deeply_immutable(self) -> None:
        with self.assertRaises(TypeError):
            DETECTION_TAXONOMY["cocoClasses"]["person"] = 79
        with self.assertRaises(TypeError):
            DETECTION_TAXONOMY["legacyNameConstraints"]["xe nâng"] = ("truck",)
        with self.assertRaises(AttributeError):
            DETECTION_TAXONOMY["legacyNameConstraints"]["xe nâng"].append("truck")


if __name__ == "__main__":
    unittest.main(verbosity=2)

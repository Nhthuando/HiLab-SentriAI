from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.metrics import evaluate_detections, iou, unified_acceptance_gate
from evaluation.run_golden import render_markdown, run


class TestGoldenMetrics(unittest.TestCase):
    def test_known_matches_buckets_confusion_and_false_alerts(self) -> None:
        truth = {
            "f1": [
                {"class": "reach_stacker", "bbox": [0.1, 0.1, 0.3, 0.3], "tags": ["far"]},
                {"class": "person", "bbox": [0.8, 0.8, 0.85, 0.85]},
            ],
            "f2": [{"class": "truck", "bbox": [0.2, 0.2, 0.5, 0.5]}],
            "f3": [],
        }
        predictions = {
            "f1": [
                {"class": "reach_stacker", "confidence": 0.9, "bbox": [0.1, 0.1, 0.3, 0.3]},
                {"class": "truck", "confidence": 0.8, "bbox": [0.1, 0.1, 0.3, 0.3]},
            ],
            "f2": [{"class": "reach_stacker", "confidence": 0.7, "bbox": [0.2, 0.2, 0.5, 0.5]}],
            "f3": [{"class": "truck", "confidence": 0.6, "bbox": [0.3, 0.3, 0.6, 0.6]}],
        }
        report = evaluate_detections(
            truth, predictions,
            frame_tags={"f3": ["static-container-only"]},
            events=[{"isFalseAlert": True}, {"isFalseAlert": False}],
            video_duration_minutes=2.0,
            events_review_complete=True,
        )
        self.assertEqual(report["perClass"]["reach_stacker"]["tp"], 1)
        self.assertEqual(report["perClass"]["reach_stacker"]["fp"], 1)
        self.assertEqual(report["perClass"]["truck"]["fn"], 1)
        self.assertEqual(report["perClass"]["reach_stacker"]["precision"]["value"], 0.5)
        self.assertEqual(report["perClass"]["reach_stacker"]["recall"]["value"], 1.0)
        self.assertEqual(report["perClass"]["reach_stacker"]["ap50"]["value"], 1.0)
        self.assertEqual(report["smallObjectRecall"], {"value": 0.0, "reason": None})
        self.assertEqual(report["farObjectRecall"], {"value": 1.0, "reason": None})
        self.assertEqual(report["truckReachStackerConfusion"]["reachStackerAsTruck"], 1)
        self.assertEqual(report["truckReachStackerConfusion"]["truckAsReachStacker"], 1)
        self.assertEqual(report["truckReachStackerConfusion"]["truckAsReachStackerRate"]["value"], 1.0)
        self.assertEqual(report["staticContainerFalseDetections"]["vehicleFalsePredictions"], 1)
        self.assertEqual(report["falseAlerts"]["perMinute"]["value"], 0.5)

    def test_zero_denominators_are_null_with_reasons(self) -> None:
        report = evaluate_detections({"empty": []}, {"empty": []})
        self.assertIsNone(report["precision"]["value"])
        self.assertTrue(report["precision"]["reason"])
        self.assertIsNone(report["recall"]["value"])
        self.assertTrue(report["smallObjectRecall"]["reason"])
        self.assertTrue(report["farObjectRecall"]["reason"])
        self.assertIsNone(report["staticContainerFalseDetections"]["perFrame"]["value"])
        self.assertIsNone(report["falseAlerts"]["perMinute"]["value"])

    def test_iou_is_exact_and_invalid_boxes_fail(self) -> None:
        self.assertAlmostEqual(iou([0, 0, 1, 1], [0.5, 0.5, 1, 1]), 0.25)
        with self.assertRaises(ValueError):
            evaluate_detections({}, {"f": [{"class": "car", "confidence": 1, "bbox": [0, 0, 2, 1]}]})

    def test_pending_manifest_blocks_class_accuracy_without_fabricated_metrics(self) -> None:
        manifest = {
            "schemaVersion": 1,
            "datasetId": "BAI-KIEM-GOLDEN-V1",
            "source": {"sourceId": "BAI-KIEM-TEST", "sourceFile": "camera.mp4", "durationMs": 10000},
            "extraction": {"timeBlockSeconds": 120},
            "frames": [{
                "frameId": "bai-kiem-000000000", "sourceId": "BAI-KIEM-TEST", "timestampMs": 0,
                "imagePath": "images/bai-kiem-000000000.jpg", "sha256": "a" * 64,
                "perceptualHash": "b" * 16, "annotationStatus": "PENDING", "labelsPath": None,
                "tags": ["interval"], "timeBlock": "BAI-KIEM-TEST-tb000", "split": "test",
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "golden-manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            report = run(path)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIsNone(report["metrics"])
        self.assertIn("PENDING", report["blockers"][0])
        self.assertIn("BLOCKED/NOT EVALUATED", render_markdown(report))

    def test_false_alert_rate_requires_complete_review_or_explicit_duration(self) -> None:
        events = [{"isFalseAlert": True}, {"isFalseAlert": False}]
        incomplete = evaluate_detections({}, {}, events=events, video_duration_minutes=10.0)
        self.assertIsNone(incomplete["falseAlerts"]["perMinute"]["value"])
        self.assertIn("incomplete", incomplete["falseAlerts"]["perMinute"]["reason"])

        reviewed_window = evaluate_detections(
            {}, {}, events=events, video_duration_minutes=10.0,
            reviewed_event_duration_minutes=2.0,
        )
        self.assertEqual(reviewed_window["falseAlerts"]["perMinute"]["value"], 0.5)
        self.assertEqual(reviewed_window["falseAlerts"]["reviewedDurationMinutes"], 2.0)

    def test_threshold_calibration_has_pr_and_confirmed_continuation_sweeps(self) -> None:
        truth = {
            "f1": [{"class": "reach_stacker", "bbox": [0.1, 0.1, 0.3, 0.3]}],
            "f2": [{"class": "reach_stacker", "bbox": [0.2, 0.2, 0.4, 0.4]}],
        }
        predictions = {
            "f1": [{
                "class": "reach_stacker", "source": "CUSTOM", "confidence": 0.35,
                "canInitiate": False, "canContinue": False, "customConfirmed": True,
                "bbox": [0.1, 0.1, 0.3, 0.3],
            }],
            "f2": [{
                "class": "reach_stacker", "source": "CUSTOM", "confidence": 0.35,
                "canInitiate": False, "canContinue": True, "customConfirmed": True,
                "bbox": [0.2, 0.2, 0.4, 0.4],
            }],
        }
        report = evaluate_detections(truth, predictions)
        self.assertEqual(
            report["thresholdCalibration"]["policy"],
            "continuation below initiation requires production canContinue=true",
        )
        group = report["thresholdCalibration"]["groups"][0]
        self.assertEqual((group["class"], group["source"]), ("reach_stacker", "custom"))
        self.assertEqual(group["prPoints"][0]["recall"]["value"], 1.0)
        candidate = next(
            item for item in group["thresholdSweep"]
            if item["initiation"] == 0.4 and item["continuation"] == 0.25
        )
        self.assertEqual(candidate["tp"], 1)
        self.assertEqual(candidate["fn"], 1)

    def test_default_test_split_and_explicit_acceptance_gates(self) -> None:
        manifest = {
            "schemaVersion": 1,
            "datasetId": "BAI-KIEM-GOLDEN-V1",
            "source": {"sourceId": "BAI-KIEM-TEST", "sourceFile": "camera.mp4", "durationMs": 360000},
            "extraction": {"timeBlockSeconds": 120},
            "frames": [
                {
                    "frameId": "cal-pending", "sourceId": "BAI-KIEM-TEST", "timestampMs": 0,
                    "imagePath": "images/cal.jpg", "sha256": "a" * 64, "perceptualHash": "b" * 16,
                    "annotationStatus": "PENDING", "labelsPath": None, "tags": ["interval"],
                    "timeBlock": "BAI-KIEM-TEST-tb000", "split": "calibration",
                },
                {
                    "frameId": "test-reviewed", "sourceId": "BAI-KIEM-TEST", "timestampMs": 240000,
                    "imagePath": "images/test.jpg", "sha256": "c" * 64, "perceptualHash": "d" * 16,
                    "annotationStatus": "ANNOTATED", "labelsPath": "labels/test.txt", "tags": ["far"],
                    "timeBlock": "BAI-KIEM-TEST-tb002", "split": "test",
                },
            ],
        }
        predictions = {
            "frameId": "test-reviewed",
            "detections": [
                {"class": "reach_stacker", "source": "CUSTOM", "confidence": 0.95, "bbox": [0.1, 0.1, 0.3, 0.3]},
                {"class": "truck", "source": "COCO", "confidence": 0.9, "bbox": [0.6, 0.6, 0.8, 0.8]},
            ],
        }
        baseline = {"metrics": {
            "falseAlerts": {"perMinute": {"value": 0.1}},
            "farObjectRecall": {"value": 0.5},
        }}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "labels").mkdir()
            (root / "labels/test.txt").write_text(
                "0 0.2 0.2 0.2 0.2\n1 0.7 0.7 0.2 0.2\n", encoding="utf-8",
            )
            manifest_path = root / "golden-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            class_map = root / "classes.json"
            class_map.write_text(json.dumps({"0": "reach_stacker", "1": "truck"}), encoding="utf-8")
            prediction_path = root / "predictions.jsonl"
            prediction_path.write_text(json.dumps(predictions) + "\n", encoding="utf-8")
            baseline_path = root / "baseline.json"
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            report = run(
                manifest_path, class_map_path=class_map, predictions_path=prediction_path,
                baseline_path=baseline_path, events_review_complete=True,
            )
        self.assertEqual(report["split"], "test")
        self.assertEqual(report["frameCounts"]["pending"], 0)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(all(gate["status"] == "PASS" for gate in report["acceptance"]["gates"].values()))

    def test_unified_acceptance_is_hash_bound_and_rejects_undefined_metrics(self) -> None:
        report = {
            "schemaVersion": 1,
            "runtimeMode": "UNIFIED",
            "datasetContentHash": "a" * 64,
            "artifactSha256": "b" * 64,
            "reviewComplete": True,
            "lockedTestSources": ["kiemhoa-hik-2", "yard-output-test"],
            "reach_stacker": {"precision": 0.91, "recall": 0.92},
            "hardNegative": {"truckToReachFalsePromotions": 0},
            "temporalContinuity": {"maxGapSeconds": 0.4},
            "performance": {"endToEndFps": 8.2},
            "baseRegression": {"passed": True},
        }
        accepted = unified_acceptance_gate(
            report, expected_dataset_hash="a" * 64, expected_artifact_hash="b" * 64,
        )
        self.assertTrue(accepted["passed"])

        report["reach_stacker"]["precision"] = None
        report["artifactSha256"] = "c" * 64
        rejected = unified_acceptance_gate(
            report, expected_dataset_hash="a" * 64, expected_artifact_hash="b" * 64,
        )
        self.assertFalse(rejected["passed"])
        self.assertIn("reach_stacker.precision is undefined", rejected["failures"])
        self.assertIn("acceptance report artifact hash does not match", rejected["failures"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

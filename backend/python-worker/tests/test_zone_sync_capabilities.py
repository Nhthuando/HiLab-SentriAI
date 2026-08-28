"""Capability-aware, atomic detection-control snapshot tests."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zone.zone_sync import (
    ZoneSynchronizer,
    _WARNED_PARTIAL_UNIFIED,
    _configured_custom_model,
)

_DEFAULT = object()


class ZoneSynchronizerCapabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        _WARNED_PARTIAL_UNIFIED.clear()
        self.sync = ZoneSynchronizer(camera_id="BAI-KIEM")
        self.zones = [{
            "id": "zone-1",
            "name": "Restricted",
            "polygon_points": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}],
            "rule_type": "PROHIBIT_SPECIFIED",
            "target_labels": ["Xe tải"],
            "is_active": True,
        }]
        self.labels = [
            {"id": "person", "vietnamese_name": "Người", "base_class": "person"},
            {"id": "truck", "vietnamese_name": "Xe tải", "base_class": "truck"},
            {"id": "reach", "vietnamese_name": "Xe nâng container", "base_class": "reach stacker"},
            {"id": "static", "vietnamese_name": "Container tĩnh", "base_class": "shipping_container"},
            # This legacy row must remain diagnostic-only; no Vietnamese-name repair is allowed.
            {"id": "legacy", "vietnamese_name": "Container", "base_class": "truck"},
        ]
        self.active = {
            "version_key": "custom-v1",
            "artifact_path": "training/models/custom-v1/best.pt",
            "artifact_sha256": "a" * 64,
            "evaluation_metrics": {"labelMap": {"Xe nâng container": "reach_stacker"}},
        }

    def _refresh(self, *, labels=None, active=_DEFAULT) -> bool:
        with (
            patch("zone.zone_sync.get_active_zones_by_camera", new=AsyncMock(return_value=self.zones)),
            patch("zone.zone_sync.get_all_object_labels", new=AsyncMock(return_value=self.labels if labels is None else labels)),
            patch("zone.zone_sync.get_active_custom_model", new=AsyncMock(return_value=self.active if active is _DEFAULT else active)),
        ):
            return asyncio.run(self.sync.refresh_now())

    def test_active_model_snapshot_routes_only_detectable_registry_classes(self) -> None:
        self.assertTrue(self._refresh())
        snapshot = self.sync.get_snapshot()

        self.assertEqual(snapshot.coco_classes, frozenset({"person", "truck"}))
        self.assertEqual(snapshot.custom_classes, frozenset({"reach_stacker"}))
        self.assertEqual(snapshot.class_to_labels["person"], ("Người",))
        self.assertEqual(snapshot.class_to_labels["truck"], ("Xe tải",))
        self.assertEqual(snapshot.class_to_labels["reach_stacker"], ("Xe nâng container",))
        self.assertNotIn("shipping_container", snapshot.class_to_labels)
        self.assertNotIn("container", snapshot.class_to_labels)
        self.assertEqual(snapshot.capabilities_by_label["Container"]["reasonCode"], "AMBIGUOUS_CONTAINER")
        self.assertEqual(snapshot.capabilities_by_label["Container tĩnh"]["reasonCode"], "CUSTOM_CLASS_NOT_IN_ACTIVE_MODEL")
        self.assertEqual(snapshot.active_model["version_key"], "custom-v1")
        self.assertEqual(
            snapshot.active_model["artifact_path"],
            str(Path(__file__).resolve().parents[2] / "data" / "training" / "models" / "custom-v1" / "best.pt"),
        )
        self.assertEqual(snapshot.active_model["artifact_sha256"], "a" * 64)
        self.assertEqual(snapshot.active_model["label_map"], {"Xe nâng container": "reach_stacker"})
        self.assertEqual(snapshot.active_model["runtime_mode"], "SUPPLEMENTAL")

    def test_unified_model_routes_all_manifest_owned_classes_to_one_set(self) -> None:
        active = {
            **self.active,
            "evaluation_metrics": {
                "runtimeMode": "UNIFIED",
                "labelMap": {
                    "person": "person",
                    "truck": "truck",
                    "reach_stacker": "reach_stacker",
                    "shipping_container": "shipping_container",
                },
            },
        }
        self.assertTrue(self._refresh(active=active))
        snapshot = self.sync.get_snapshot()
        self.assertEqual(snapshot.active_model["runtime_mode"], "UNIFIED")
        self.assertEqual(snapshot.coco_classes, frozenset())
        self.assertEqual(
            snapshot.custom_classes,
            frozenset({"person", "truck", "reach_stacker", "shipping_container"}),
        )

    def test_incomplete_unified_model_falls_back_to_base_coco(self) -> None:
        active = {
            **self.active,
            "evaluation_metrics": {
                "runtimeMode": "UNIFIED",
                "labelMap": {"person": "person", "reach_stacker": "reach_stacker"},
            },
        }
        self.assertTrue(self._refresh(active=active))
        snapshot = self.sync.get_snapshot()
        self.assertIsNone(snapshot.active_model)
        self.assertEqual(snapshot.coco_classes, frozenset({"person", "truck"}))
        self.assertEqual(snapshot.custom_classes, frozenset())
        self.assertEqual(
            snapshot.capabilities_by_label[next(
                name for name in snapshot.capabilities_by_label if "container" in name.casefold()
            )]["reasonCode"],
            "INVALID_ACTIVE_MANIFEST",
        )

    def test_owner_approved_partial_unified_model_keeps_supported_classes(self) -> None:
        active = {
            **self.active,
            "evaluation_metrics": {
                "runtimeMode": "UNIFIED",
                "labelMap": {
                    "person": "person",
                    "reach_stacker": "reach_stacker",
                },
                "manualProductionApproval": {
                    "approved": True,
                    "allowPartialUnified": True,
                },
            },
        }
        with patch("zone.zone_sync.logger.warning") as warning:
            self.assertTrue(self._refresh(active=active))
            self.assertTrue(self._refresh(active=active))
        partial_warnings = [
            call for call in warning.call_args_list
            if "Owner-approved partial UNIFIED coverage" in str(call)
        ]
        self.assertEqual(len(partial_warnings), 1)
        snapshot = self.sync.get_snapshot()

        self.assertEqual(snapshot.active_model["runtime_mode"], "UNIFIED")
        self.assertTrue(snapshot.active_model["allow_partial_unified"])
        self.assertEqual(snapshot.coco_classes, frozenset())
        self.assertEqual(snapshot.custom_classes, frozenset({"person", "reach_stacker"}))
        truck_display_name = next(
            item["vietnamese_name"] for item in self.labels if item["base_class"] == "truck"
            and "container" not in item["vietnamese_name"].casefold()
        )
        self.assertEqual(
            snapshot.capabilities_by_label[truck_display_name]["reasonCode"],
            "UNIFIED_CLASS_NOT_IN_ACTIVE_MODEL",
        )

    def test_no_active_model_keeps_coco_and_marks_custom_unavailable(self) -> None:
        self.assertTrue(self._refresh(active=None))
        snapshot = self.sync.get_snapshot()

        self.assertIsNone(snapshot.active_model)
        self.assertEqual(snapshot.coco_classes, frozenset({"person", "truck"}))
        self.assertEqual(snapshot.custom_classes, frozenset())
        self.assertNotIn("reach_stacker", snapshot.class_to_labels)
        self.assertEqual(
            snapshot.capabilities_by_label["Xe nâng container"]["reasonCode"],
            "NO_ACTIVE_CUSTOM_MODEL",
        )

    def test_failed_refresh_preserves_the_exact_previous_snapshot(self) -> None:
        self.assertTrue(self._refresh())
        before = self.sync.get_snapshot()
        with patch("zone.zone_sync.get_active_zones_by_camera", new=AsyncMock(side_effect=RuntimeError("database unavailable"))):
            self.assertFalse(asyncio.run(self.sync.refresh_now()))

        self.assertIs(self.sync.get_snapshot(), before)
        with self.assertRaises(TypeError):
            before.class_to_labels["truck"] = ("mutated",)

    def test_explicit_reviewed_configured_model_bridge_is_checksum_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory)
            model_dir = data_root / "training" / "models" / "legacy"
            model_dir.mkdir(parents=True)
            artifact = model_dir / "best.pt"
            artifact.write_bytes(b"reviewed-model")
            (model_dir / "labels.json").write_text(
                json.dumps({"Xe nâng": "reach stacker"}), encoding="utf-8"
            )
            (model_dir / "evaluation.json").write_text(json.dumps({
                "qualityGate": {"passed": True},
                "baseRegression": {"passed": True},
            }), encoding="utf-8")

            configured = _configured_custom_model({
                "CUSTOM_AUGMENT_FORCE_DEFAULT": "true",
                "CUSTOM_AUGMENT_ARTIFACT": "training/models/legacy/best.pt",
                "CUSTOM_AUGMENT_VERSION_KEY": "custom-legacy",
                "CUSTOM_AUGMENT_SHA256": hashlib.sha256(b"reviewed-model").hexdigest(),
            }, data_root)

        self.assertIsNotNone(configured)
        assert configured is not None
        self.assertEqual(configured["version_key"], "custom-legacy")
        self.assertEqual(configured["evaluation_metrics"]["labelMap"], {"Xe nâng": "reach stacker"})
        self.assertEqual(len(configured["artifact_sha256"]), 64)

    def test_manual_candidate_requires_metadata_and_environment_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory)
            model_dir = data_root / "training" / "models" / "candidate"
            model_dir.mkdir(parents=True)
            artifact = model_dir / "best.pt"
            artifact.write_bytes(b"manual-candidate")
            artifact_sha256 = hashlib.sha256(b"manual-candidate").hexdigest()
            (model_dir / "labels.json").write_text(
                json.dumps({"Reach stacker": "reach_stacker"}), encoding="utf-8"
            )
            (model_dir / "evaluation.json").write_text(json.dumps({
                "manualProductionApproval": {
                    "approved": True,
                    "allowPartialUnified": True,
                    "artifactSha256": artifact_sha256,
                },
                "runtimeMode": "UNIFIED",
                "qualityGate": {"passed": False},
                "baseRegression": {"passed": True},
            }), encoding="utf-8")
            base_environment = {
                "CUSTOM_AUGMENT_FORCE_DEFAULT": "true",
                "CUSTOM_AUGMENT_ARTIFACT": "training/models/candidate/best.pt",
                "CUSTOM_AUGMENT_VERSION_KEY": "custom-candidate",
                "CUSTOM_AUGMENT_SHA256": artifact_sha256,
            }

            self.assertIsNone(_configured_custom_model(base_environment, data_root))
            configured = _configured_custom_model({
                **base_environment,
                "CUSTOM_AUGMENT_MANUAL_CANDIDATE": "true",
            }, data_root)

        self.assertIsNotNone(configured)
        assert configured is not None
        self.assertEqual(configured["version_key"], "custom-candidate")
        self.assertEqual(configured["evaluation_metrics"]["runtimeMode"], "UNIFIED")
        self.assertEqual(
            configured["evaluation_metrics"]["manualProductionApproval"]["artifactSha256"],
            artifact_sha256,
        )

    def test_manual_candidate_rejects_legacy_or_unbound_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory)
            model_dir = data_root / "training" / "models" / "candidate"
            model_dir.mkdir(parents=True)
            artifact = model_dir / "best.pt"
            artifact.write_bytes(b"manual-candidate")
            artifact_sha256 = hashlib.sha256(b"manual-candidate").hexdigest()
            (model_dir / "labels.json").write_text(
                json.dumps({"Reach stacker": "reach_stacker"}), encoding="utf-8"
            )
            environment = {
                "CUSTOM_AUGMENT_FORCE_DEFAULT": "true",
                "CUSTOM_AUGMENT_MANUAL_CANDIDATE": "true",
                "CUSTOM_AUGMENT_ARTIFACT": "training/models/candidate/best.pt",
                "CUSTOM_AUGMENT_VERSION_KEY": "custom-candidate",
                "CUSTOM_AUGMENT_SHA256": artifact_sha256,
            }
            rejected_approvals = (
                {"manualTestApproved": True},
                {"manualProductionApproval": {
                    "approved": False,
                    "allowPartialUnified": True,
                    "artifactSha256": artifact_sha256,
                }},
                {"manualProductionApproval": {
                    "approved": True,
                    "allowPartialUnified": False,
                    "artifactSha256": artifact_sha256,
                }},
                {"manualProductionApproval": {
                    "approved": True,
                    "allowPartialUnified": True,
                    "artifactSha256": "f" * 64,
                }},
            )

            for approval_metadata in rejected_approvals:
                with self.subTest(approval_metadata=approval_metadata):
                    (model_dir / "evaluation.json").write_text(json.dumps({
                        **approval_metadata,
                        "runtimeMode": "UNIFIED",
                        "qualityGate": {"passed": False},
                        "baseRegression": {"passed": True},
                    }), encoding="utf-8")
                    self.assertIsNone(_configured_custom_model(environment, data_root))


if __name__ == "__main__":
    unittest.main(verbosity=2)

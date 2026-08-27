from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.v9_profile import EXPECTED_V9_CLASSES, V9ProfileError, load_v9_profile


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROFILE_PATH = PROJECT_ROOT / "backend/config/baikiem-v9-profile.json"


class V9ProfileTests(unittest.TestCase):
    def test_profile_has_exact_class_order_and_no_static_container(self) -> None:
        profile = load_v9_profile(PROFILE_PATH)
        self.assertEqual(profile.classes, EXPECTED_V9_CLASSES)
        self.assertNotIn("shipping_container", profile.classes)
        self.assertEqual(profile.minimum_end_to_end_fps, 8.0)
        self.assertEqual(profile.selection.train_val_target_frames, 1000)
        self.assertEqual(profile.selection.locked_target_frames, 200)

    def test_profile_rejects_boolean_threshold_and_unknown_field(self) -> None:
        payload = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        payload["acceptance"]["macroPrecision"] = True
        payload["unexpected"] = "unsafe"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(V9ProfileError):
                load_v9_profile(path, PROJECT_ROOT / "backend/config/detection-taxonomy.json")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.local_video_dataset import CLASS_NAMES
from training.tiled_local_video_dataset import export_tiled_reach_snapshot


class TestTiledLocalVideoDataset(unittest.TestCase):
    @staticmethod
    def _reviewed_snapshot(root: Path) -> Path:
        snapshot = root / "reviewed"
        frames: list[dict[str, object]] = []
        for split, value, labels in (
            ("train", 0, "5 0.25 0.25 0.10 0.10\n"),
            ("val", 255, ""),
            ("test", 127, "5 0.50 0.50 0.10 0.10\n"),
        ):
            image_dir = snapshot / "images" / split
            label_dir = snapshot / "labels" / split
            image_dir.mkdir(parents=True)
            label_dir.mkdir(parents=True)
            frame_id = f"frame-{split}"
            ok, encoded = cv2.imencode(".jpg", np.full((480, 640, 3), value, dtype=np.uint8))
            if not ok:
                raise AssertionError("fixture image encoding failed")
            payload = encoded.tobytes()
            image_path = image_dir / f"{frame_id}.jpg"
            label_path = label_dir / f"{frame_id}.txt"
            image_path.write_bytes(payload)
            label_path.write_text(labels, encoding="utf-8")
            frames.append({
                "frameId": frame_id,
                "sourceId": f"source-{split}",
                "timestampMs": 0,
                "split": split,
                "imagePath": image_path.relative_to(snapshot).as_posix(),
                "labelsPath": label_path.relative_to(snapshot).as_posix(),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "reviewStatus": "REVIEWED",
            })
        manifest = {
            "schemaVersion": 3,
            "datasetKind": "LOCAL_VIDEO_REVIEWED",
            "datasetId": "fixture",
            "contentHash": "a" * 64,
            "reviewStatus": "REVIEWED",
            "classes": list(CLASS_NAMES),
            "frames": frames,
            "sources": [
                {"sourceId": f"source-{split}", "sourceFile": f"source-{split}.asf", "fps": 20.0}
                for split in ("train", "val", "test")
            ],
        }
        (snapshot / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return snapshot

    def test_exports_only_train_and_val_tiles_with_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reviewed = self._reviewed_snapshot(root)
            result = export_tiled_reach_snapshot(
                reviewed, root / "output", roi=(0.0, 0.0, 1.0, 1.0),
                crop_size=320, overlap=0.0, max_tiles=4,
            )
            manifest = json.loads(Path(result["manifestPath"]).read_text(encoding="utf-8"))
            records = [*manifest["samples"], *manifest["negativeMedia"]]
            self.assertEqual(result["cropCount"], 8)
            self.assertEqual(len(manifest["samples"]), 1)
            self.assertEqual({record["split"] for record in records}, {"train", "val"})
            self.assertEqual(manifest["origin"]["inputContentHash"], "a" * 64)
            self.assertTrue(all((Path(result["directory"]) / record["mediaPath"]).is_file() for record in records))

    def test_rejects_locked_test_tile_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "train and val"):
                export_tiled_reach_snapshot(
                    self._reviewed_snapshot(root), root / "output", splits=("test",),
                )

    def test_native_export_uses_original_video_frames_without_caching_all_frames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reviewed = self._reviewed_snapshot(root)
            video_root = root / "videos"
            video_root.mkdir()
            for split in ("train", "val"):
                (video_root / f"source-{split}.asf").write_bytes(b"video")
            ffmpeg = root / "ffmpeg.exe"
            ffmpeg.write_bytes(b"executable")
            completed = []
            for value in (64, 128):
                ok, encoded = cv2.imencode(".png", np.full((720, 1280, 3), value, dtype=np.uint8))
                self.assertTrue(ok)
                completed.append(SimpleNamespace(returncode=0, stdout=encoded.tobytes(), stderr=b""))

            with patch("stream.native_video_frames.subprocess.run", side_effect=completed) as run:
                result = export_tiled_reach_snapshot(
                    reviewed, root / "output", roi=(0.0, 0.0, 1.0, 1.0),
                    crop_size=640, overlap=0.0, max_tiles=4,
                    video_root=video_root, ffmpeg_path=ffmpeg,
                )

            manifest = json.loads(Path(result["manifestPath"]).read_text(encoding="utf-8"))
            self.assertEqual(run.call_count, 2)
            self.assertTrue(manifest["origin"]["nativeSourceFrames"])
            self.assertEqual(manifest["origin"]["nativeFrameDecoder"], "ffmpeg-fast-seek")


if __name__ == "__main__":
    unittest.main(verbosity=2)

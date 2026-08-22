"""Regression checks for recoverable custom-model training failures."""
from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.runner import _is_system_memory_error


class TrainingRunnerTests(unittest.TestCase):
    def test_marks_opencv_host_memory_failure_as_recoverable(self) -> None:
        error = RuntimeError(
            "cv2.error: OpenCV error: (-4:Insufficient memory) Failed to allocate bytes in function"
        )

        self.assertTrue(_is_system_memory_error(error))

    def test_does_not_hide_unrelated_training_failure(self) -> None:
        self.assertFalse(_is_system_memory_error(RuntimeError("dataset yaml is invalid")))


if __name__ == "__main__":
    unittest.main()

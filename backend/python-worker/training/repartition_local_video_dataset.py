"""Create an immutable active-learning split from a reviewed snapshot policy."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from training.local_video_dataset import repartition_reviewed_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    target = repartition_reviewed_snapshot(
        args.snapshot,
        args.output_root,
        dataset_id=str(policy["datasetId"]),
        source_policies=policy["sourcePolicies"],
    )
    print(json.dumps({"snapshot": str(target), "manifest": str(target / "manifest.json")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

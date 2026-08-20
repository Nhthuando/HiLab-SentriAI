import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detection.gate_pipeline import GatePipeline


async def run_benchmark(source: str, frames: int, width: int, height: int) -> None:
    pipeline = GatePipeline(
        camera_id="GATE-01",
        source=source,
        target_fps=15.0,
        resolution=(width, height),
    )
    started = time.time()
    detections = 0
    try:
        for _ in range(frames):
            result = await pipeline.process_gate_frame()
            detections += len(result.get("detections", []))
        await asyncio.sleep(0.5)
        elapsed = time.time() - started
        print(
            "frames={frames} elapsed={elapsed:.2f}s processing_fps={fps:.1f} "
            "live_fps={live_fps} detections={detections} yolo_device={device} "
            "alpr={providers} resolution={resolution}".format(
                frames=frames,
                elapsed=elapsed,
                fps=frames / elapsed,
                live_fps=pipeline.fps_measured,
                detections=detections,
                device=pipeline.detector.device,
                providers=pipeline.lpr_reader.providers,
                resolution=pipeline.resolution,
            )
        )
    finally:
        await pipeline.stop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=540)
    args = parser.parse_args()
    asyncio.run(run_benchmark(args.source, args.frames, args.width, args.height))


if __name__ == "__main__":
    main()

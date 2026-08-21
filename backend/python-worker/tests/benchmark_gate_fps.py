import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detection.gate_pipeline import GatePipeline


async def run_benchmark(
    source: str,
    frames: int,
    width: int,
    height: int,
    start_ms: int = 0,
    realtime: bool = False,
) -> None:
    pipeline = GatePipeline(
        camera_id="GATE-01",
        source=source,
        target_fps=15.0,
        resolution=(width, height),
    )
    started = time.time()
    detections = 0
    observed = {}
    try:
        if start_ms > 0:
            pipeline.reader.seek_ms(start_ms)
            pipeline.reset_tracking_state()
        for _ in range(frames):
            frame_started = time.time()
            result = await pipeline.process_gate_frame()
            detections += len(result.get("detections", []))
            for detection in result.get("detections", []):
                plate = detection.get("plate")
                if plate:
                    observed[plate] = max(
                        float(detection.get("confidence", 0.0)),
                        observed.get(plate, 0.0),
                    )
            if realtime:
                await asyncio.sleep(max(0.0, (1.0 / pipeline.target_fps) - (time.time() - frame_started)))
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
        print("observed_plates={}".format(observed))
        print(
            "track_candidates={}".format(
                {
                    track_id: (track.best_plate, round(track.best_conf, 3), track.bbox_confirmation_count)
                    for track_id, track in pipeline.tracker.tracks.items()
                    if track.best_plate
                }
            )
        )
        print("finalized_events={}".format(sorted(pipeline._recent_events)))
    finally:
        await pipeline.stop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=540)
    parser.add_argument("--start-ms", type=int, default=0)
    parser.add_argument("--realtime", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        run_benchmark(
            args.source,
            args.frames,
            args.width,
            args.height,
            start_ms=args.start_ms,
            realtime=args.realtime,
        )
    )


if __name__ == "__main__":
    main()

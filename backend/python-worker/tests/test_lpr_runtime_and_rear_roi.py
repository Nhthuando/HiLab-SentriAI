import os
import sys
import asyncio
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detection.lpr import LicensePlateReader, validate_and_normalize_plate
from detection.plate_tracker import PlateTracker, compute_iou


def test_vehicle_detector_defaults_to_yolo11n():
    import inspect
    from detection.detector import YoloDetector

    default_model = inspect.signature(YoloDetector.__init__).parameters["model_path"].default
    assert default_model == "yolo11n.pt"


def test_top_view_vehicle_alias_requires_large_vertical_gate_geometry():
    from detection.detector import YoloDetector

    assert YoloDetector._is_high_angle_vehicle_alias([316, 92, 594, 535], 960, 540)
    assert YoloDetector._is_high_angle_vehicle_alias([338, 80, 596, 456], 960, 540)
    assert not YoloDetector._is_high_angle_vehicle_alias([20, 20, 80, 110], 960, 540)
    assert not YoloDetector._is_high_angle_vehicle_alias([200, 300, 700, 500], 960, 540)


class FakeALPR:
    def predict(self, image):
        h, w = image.shape[:2]
        if w < 350:
            return []
        return [
            SimpleNamespace(
                ocr=SimpleNamespace(text="15R00517", confidence=[0.72] * 8),
                detection=SimpleNamespace(
                    bounding_box=SimpleNamespace(
                        x1=int(w * 0.60),
                        y1=int(h * 0.58),
                        x2=int(w * 0.82),
                        y2=int(h * 0.66),
                    )
                ),
            )
        ]


class ClearPlateALPR:
    def __init__(self):
        self.calls = 0

    def predict(self, image):
        self.calls += 1
        h, w = image.shape[:2]
        return [
            SimpleNamespace(
                ocr=SimpleNamespace(text="15R10517", confidence=[1.0] * 8),
                detection=SimpleNamespace(
                    bounding_box=SimpleNamespace(
                        x1=int(w * 0.72),
                        y1=int(h * 0.74),
                        x2=int(w * 0.88),
                        y2=int(h * 0.82),
                    )
                ),
            )
        ]


class RecessedPlateALPR:
    def __init__(self):
        self.calls = 0

    def predict(self, image):
        self.calls += 1
        if self.calls == 1:
            return []
        h, w = image.shape[:2]
        return [
            SimpleNamespace(
                ocr=SimpleNamespace(text="15H03203", confidence=[0.81] * 8),
                detection=SimpleNamespace(
                    bounding_box=SimpleNamespace(
                        x1=int(w * 0.78),
                        y1=int(h * 0.65),
                        x2=int(w * 0.96),
                        y2=int(h * 0.75),
                    )
                ),
            )
        ]


class TightCropOCR:
    def predict(self, image):
        return SimpleNamespace(text="15R10253", confidence=[0.90] * 8)


class AmbiguousGreenPlateALPR:
    def __init__(self):
        self.ocr = TightCropOCR()

    def predict(self, image):
        h, w = image.shape[:2]
        return [
            SimpleNamespace(
                ocr=SimpleNamespace(text="16R10253", confidence=[0.99] * 8),
                detection=SimpleNamespace(
                    bounding_box=SimpleNamespace(
                        x1=int(w * 0.70),
                        y1=int(h * 0.76),
                        x2=int(w * 0.78),
                        y2=int(h * 0.82),
                    )
                ),
            )
        ]


class StationaryOnlyPlateALPR:
    def predict(self, image):
        h, w = image.shape[:2]
        if w < 1000:
            return []
        return [
            SimpleNamespace(
                ocr=SimpleNamespace(text="15RM07197", confidence=[0.91] * 9),
                detection=SimpleNamespace(
                    bounding_box=SimpleNamespace(
                        x1=int(w * 0.52),
                        y1=int(h * 0.58),
                        x2=int(w * 0.68),
                        y2=int(h * 0.73),
                    )
                ),
            )
        ]


class RecessedStationaryPlateALPR:
    def predict(self, image):
        h, w = image.shape[:2]
        if not (880 <= w <= 1040 and h >= 680):
            return []
        return [
            SimpleNamespace(
                ocr=SimpleNamespace(text="15R10253", confidence=[0.96] * 8),
                detection=SimpleNamespace(
                    bounding_box=SimpleNamespace(
                        x1=int(w * 0.66),
                        y1=int(h * 0.55),
                        x2=int(w * 0.88),
                        y2=int(h * 0.72),
                    )
                ),
            )
        ]


def test_rear_roi_plate_detection_maps_tight_bbox_to_vehicle_crop():
    reader = LicensePlateReader.__new__(LicensePlateReader)
    reader._alpr = FakeALPR()

    vehicle_crop = np.zeros((420, 520, 3), dtype=np.uint8)
    full_frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    candidates = reader.scan_plate_from_frame_or_vehicle(full_frame, vehicle_crop, [700, 120, 1220, 540])

    assert candidates
    best = candidates[0]
    assert best["plate"] == "15R-005.17"
    assert best["confidence"] == 0.72
    x1, y1, x2, y2 = best["bbox_in_crop"]
    assert 0 <= x1 < x2 <= 520
    assert 0 <= y1 < y2 <= 420
    assert (x2 - x1) < 160
    assert best["source"] in {"vehicle_full_raw", "vehicle_lower_raw", "tractor_wheel_side_raw"}


def test_clear_plate_uses_raw_full_vehicle_without_enhanced_fallback():
    reader = LicensePlateReader.__new__(LicensePlateReader)
    reader._alpr = ClearPlateALPR()

    vehicle_crop = np.zeros((420, 520, 3), dtype=np.uint8)
    candidates = reader.scan_plate_from_frame_or_vehicle(
        np.zeros((720, 1280, 3), dtype=np.uint8),
        vehicle_crop,
        [700, 120, 1220, 540],
    )

    assert reader._alpr.calls == 1
    assert candidates[0]["plate"] == "15R-105.17"
    assert candidates[0]["confidence"] == 1.0
    assert candidates[0]["source"] == "vehicle_full_raw"
    assert not candidates[0]["enhanced"]


def test_recessed_rear_plate_uses_raw_roi_fallback_and_maps_inside_vehicle():
    reader = LicensePlateReader.__new__(LicensePlateReader)
    reader._alpr = RecessedPlateALPR()

    vehicle_crop = np.zeros((420, 520, 3), dtype=np.uint8)
    candidates = reader.scan_plate_from_frame_or_vehicle(
        np.zeros((720, 1280, 3), dtype=np.uint8),
        vehicle_crop,
        [700, 120, 1220, 540],
    )

    assert reader._alpr.calls > 1
    assert candidates[0]["plate"] == "15H-032.03"
    assert candidates[0]["source"] != "vehicle_full_raw"
    x1, y1, x2, y2 = candidates[0]["bbox_in_crop"]
    assert 0 <= x1 < x2 <= 520
    assert 0 <= y1 < y2 <= 420


def test_tight_crop_refinement_preserves_15_prefix_as_temporal_evidence():
    reader = LicensePlateReader.__new__(LicensePlateReader)
    reader._alpr = AmbiguousGreenPlateALPR()
    reader._alternate_ocr = None

    candidates = reader.scan_plate_from_frame_or_vehicle(
        np.zeros((720, 1280, 3), dtype=np.uint8),
        np.zeros((420, 520, 3), dtype=np.uint8),
        [700, 120, 1220, 540],
    )

    assert any(c["plate"] == "15R-102.53" and c["source"] == "plate_tight_raw" for c in candidates)


def test_stationary_vehicle_uses_extra_rear_scan_without_changing_moving_path():
    reader = LicensePlateReader.__new__(LicensePlateReader)
    reader._alpr = StationaryOnlyPlateALPR()
    reader._alternate_ocr = None
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    crop = np.zeros((420, 520, 3), dtype=np.uint8)

    moving = reader.scan_plate_from_frame_or_vehicle(frame, crop, [700, 120, 1220, 540])
    stationary = reader.scan_plate_from_frame_or_vehicle(
        frame,
        crop,
        [700, 120, 1220, 540],
        stationary=True,
    )

    assert moving == []
    assert stationary[0]["plate"] == "15RM-071.97"
    assert stationary[0]["source"].startswith("stationary_rear_")


def test_stationary_recessed_rear_scan_finds_partly_occluded_green_plate():
    reader = LicensePlateReader.__new__(LicensePlateReader)
    reader._alpr = RecessedStationaryPlateALPR()
    reader._alternate_ocr = None
    frame = np.zeros((900, 1600, 3), dtype=np.uint8)
    crop = np.zeros((420, 520, 3), dtype=np.uint8)

    moving = reader.scan_plate_from_frame_or_vehicle(frame, crop, [700, 300, 1220, 720])
    stationary = reader.scan_plate_from_frame_or_vehicle(
        frame,
        crop,
        [700, 300, 1220, 720],
        stationary=True,
    )

    assert moving == []
    assert stationary[0]["plate"] == "15R-102.53"
    assert stationary[0]["source"].startswith("stationary_recessed_rear_")


def test_stationary_tracking_settles_without_waiting_for_motion():
    tracker = PlateTracker()
    track_id = tracker.match_or_create_track([700, 200, 1500, 880], 100.0, lane="IN_1")
    track = tracker.update_track(
        track_id,
        [700, 200, 1500, 880],
        None,
        "",
        "SCANNING",
        0.85,
        100.0,
    )
    track.lane = "IN_1"

    tracker.update_track(track_id, [701, 200, 1501, 880], None, "", "SCANNING", 0.85, 100.2)
    tracker.update_track(track_id, [701, 200, 1501, 880], None, "", "SCANNING", 0.85, 101.2)

    assert track.is_stationary(101.2)


def test_gate_ocr_is_not_starved_when_measured_fps_is_below_fourteen():
    from detection.gate_pipeline import GatePipeline

    class FakeReader:
        def read_frame(self):
            return True, np.zeros((720, 1280, 3), dtype=np.uint8)

        def get_timecode(self):
            return "00:01"

    class FakeBuffer:
        def append(self, frame, now):
            return None

    class FakeDetector:
        def detect(self, frame):
            return [{"class": "truck", "bbox": [600, 150, 1100, 680]}]

    class FakeTracker:
        def __init__(self):
            self.tracks = {}

        def match_or_create_track(self, bbox, now):
            return "V001"

        def update_track(self, **kwargs):
            self.tracks["V001"] = SimpleNamespace(vehicle_bbox=kwargs["vehicle_bbox"])

        def update_related_plate_tracks(self, track_id, bbox, now):
            return None

        def get_live_detections(self, now, min_confidence=0.0):
            return []

    async def exercise():
        pipeline = GatePipeline.__new__(GatePipeline)
        pipeline.reader = FakeReader()
        pipeline.buffer = FakeBuffer()
        pipeline.detector = FakeDetector()
        pipeline.tracker = FakeTracker()
        pipeline.camera_id = "GATE-01"
        pipeline.frame_count = 0
        pipeline._last_zone_sync = 10**12
        pipeline._last_vehicle_status_sync = 10**12
        pipeline._active_zones = []
        pipeline._ai_busy = False
        pipeline._last_ocr_dispatch = 0.0
        pipeline._ocr_interval_seconds = 0.35
        pipeline._yolo_stride = 1
        pipeline.fps_measured = 8.0
        pipeline.target_fps = 15.0
        pipeline._fps_counter = 0
        pipeline._last_fps_calc = 10**12
        pipeline._sync_calls = 0

        async def fake_ocr(frame, detections, now, generation=None):
            pipeline._sync_calls += 1

        pipeline._run_ai_in_background = fake_ocr
        await pipeline.process_gate_frame()
        await asyncio.sleep(0)
        assert pipeline._sync_calls == 1

    asyncio.run(exercise())


def test_delayed_ocr_bbox_is_projected_to_latest_moving_vehicle_position():
    old_vehicle = [600, 150, 1000, 650]
    new_vehicle = [660, 170, 1100, 690]
    old_plate = [900, 540, 980, 580]

    projected = PlateTracker.project_box_between_vehicle_boxes(old_plate, old_vehicle, new_vehicle)

    assert projected[0] > old_plate[0]
    assert projected[1] > old_plate[1]
    assert projected[2] <= new_vehicle[2]
    assert projected[3] <= new_vehicle[3]


def test_runtime_provider_selection_prefers_cuda_when_available():
    providers, reason = LicensePlateReader._select_onnx_providers(
        ["CUDAExecutionProvider", "CPUExecutionProvider"]
    )

    assert providers[0] == "CUDAExecutionProvider"
    assert reason == "auto_cuda"


def test_validate_plate_rejects_camera_overlay_words():
    is_valid, plate = validate_and_normalize_plate("CAMERA-01")

    assert not is_valid
    assert plate == ""


def test_plate_tracker_keeps_best_plate_and_bbox_for_one_vehicle():
    tracker = PlateTracker(smoothing_alpha=0.8)
    now = 100.0
    track_id = tracker.match_or_create_track([100, 100, 500, 420], now)

    tracker.update_track(
        track_id=track_id,
        vehicle_bbox=[100, 100, 500, 420],
        plate_bbox=[350, 330, 430, 365],
        plate_text="15R-106.17",
        status="STRANGER",
        conf=0.96,
        now=now,
    )
    tracker.update_track(
        track_id=track_id,
        vehicle_bbox=[104, 100, 504, 420],
        plate_bbox=[354, 330, 434, 365],
        plate_text="15R-106.17",
        status="STRANGER",
        conf=0.95,
        now=now + 0.05,
    )
    tracker.update_track(
        track_id=track_id,
        vehicle_bbox=[104, 100, 504, 420],
        plate_bbox=[120, 130, 300, 230],
        plate_text="18R-406.17",
        status="STRANGER",
        conf=0.55,
        now=now + 0.1,
    )

    detections = tracker.get_live_detections(now + 1.0)

    assert len(detections) == 1
    assert detections[0]["plate"] == "15R-106.17"
    assert detections[0]["confidence"] == 0.96
    x1, y1, x2, y2 = detections[0]["bbox"]
    assert x1 > 300
    assert y1 > 300
    assert x2 - x1 < 120


def test_plate_tracker_collapses_duplicate_bboxes_to_one_vehicle_result():
    tracker = PlateTracker(smoothing_alpha=0.8)
    now = 200.0
    vehicle_bbox = [620, 120, 1080, 430]
    track_id = tracker.match_or_create_track(vehicle_bbox, now)

    reads = [
        ("16R-106.17", [780, 345, 875, 382], 0.97, now),
        ("16R-106.12", [782, 346, 877, 383], 0.94, now + 0.05),
        ("15R-135.17", [786, 348, 880, 386], 0.97, now + 0.10),
        ("15R-105.17", [784, 347, 878, 385], 0.96, now + 0.15),
        ("15R-105.17", [785, 347, 879, 385], 0.95, now + 0.20),
    ]

    for plate, plate_bbox, conf, ts in reads:
        track = tracker.update_track(
            track_id=track_id,
            vehicle_bbox=vehicle_bbox,
            plate_bbox=plate_bbox,
            plate_text=plate,
            status="STRANGER",
            conf=conf,
            now=ts,
        )
        track.last_vehicle_seen = ts

    detections = tracker.get_live_detections(now + 1.10)
    assert len(detections) == 1
    assert detections[0]["track_id"] == track_id
    assert detections[0]["plate"] == "15R-105.17"

    track = tracker.tracks[track_id]
    assert track.should_emit_event(now + 1.10)
    track.event_emitted = True
    assert not track.should_emit_event(now + 0.85)


def test_single_late_wrong_read_cannot_emit_before_stable_green_truck_plate():
    tracker = PlateTracker(smoothing_alpha=0.8)
    vehicle_bbox = [680, 0, 1280, 715]
    track_id = tracker.match_or_create_track(vehicle_bbox, 263.0)

    tracker.update_track(
        track_id=track_id,
        vehicle_bbox=vehicle_bbox,
        plate_bbox=[1150, 588, 1210, 635],
        plate_text="76R-100.55",
        status="STRANGER",
        conf=0.70,
        now=268.60,
    )
    track = tracker.tracks[track_id]
    assert not track.should_emit_event(268.60)
    early = tracker.get_live_detections(268.60)
    assert len(early) == 1
    assert early[0]["plate"] == ""
    assert early[0]["lpr_status"] == "SCANNING"
    assert not early[0]["is_locked"]

    tracker.update_track(
        track_id=track_id,
        vehicle_bbox=vehicle_bbox,
        plate_bbox=[1128, 576, 1175, 618],
        plate_text="16R-102.53",
        status="STRANGER",
        conf=0.95,
        now=269.00,
    )
    assert track.best_plate == "16R-102.53"
    assert not track.should_emit_event(269.00)
    early = tracker.get_live_detections(269.00)
    assert len(early) == 1
    assert early[0]["plate"] == ""

    tracker.update_track(
        track_id=track_id,
        vehicle_bbox=vehicle_bbox,
        plate_bbox=[1126, 575, 1174, 618],
        plate_text="16R-102.53",
        status="STRANGER",
        conf=0.93,
        now=269.40,
    )
    assert track.best_plate == "16R-102.53"
    assert track.best_conf == 0.95
    assert not track.should_emit_event(269.40)
    assert track.should_emit_event(270.20)
    track.last_vehicle_seen = 270.0
    assert tracker.get_live_detections(270.20)[0]["plate"] == "16R-102.53"


def test_repeated_correct_plate_can_replace_an_initial_high_confidence_variant():
    tracker = PlateTracker()
    vehicle_bbox = [620, 120, 1080, 430]
    track_id = tracker.match_or_create_track(vehicle_bbox, 100.0)

    for plate, conf, now in (
        ("76R-105.17", 0.97, 100.0),
        ("15R-105.17", 0.95, 100.4),
        ("15R-105.17", 0.94, 100.8),
    ):
        tracker.update_track(
            track_id=track_id,
            vehicle_bbox=vehicle_bbox,
            plate_bbox=[900, 340, 970, 385],
            plate_text=plate,
            status="STRANGER",
            conf=conf,
            now=now,
        )

    track = tracker.tracks[track_id]
    assert track.best_plate == "15R-105.17"
    assert track.best_conf == 0.95
    assert not track.should_emit_event(100.8)
    assert track.should_emit_event(101.6)


def test_character_consensus_resolves_16r_to_repeated_15r_without_hardcoding():
    tracker = PlateTracker()
    vehicle_bbox = [650, 80, 1100, 650]
    track_id = tracker.match_or_create_track(vehicle_bbox, 300.0)

    observations = (
        ("16R-102.53", 0.99, [{"plate": "15R-102.53", "confidence": 0.90}], 300.0),
        ("16R-102.53", 0.98, [{"plate": "15R-102.69", "confidence": 0.90}], 300.3),
        ("15R-102.63", 0.99, [{"plate": "15R-102.53", "confidence": 0.84}], 300.6),
        ("15R-102.53", 0.99, [{"plate": "15R-102.53", "confidence": 0.95}], 300.9),
    )
    for plate, confidence, variants, now in observations:
        tracker.update_track(
            track_id=track_id,
            vehicle_bbox=vehicle_bbox,
            plate_bbox=[880, 520, 930, 550],
            plate_text=plate,
            status="STRANGER",
            conf=confidence,
            now=now,
            variants=variants,
        )

    track = tracker.tracks[track_id]
    assert track.best_plate == "15R-102.53"
    assert not track.should_emit_event(300.9)
    assert track.should_emit_event(301.7)


def test_character_consensus_uses_material_15_evidence_for_5_6_ambiguity():
    tracker = PlateTracker()
    vehicle_bbox = [650, 80, 1100, 650]
    track_id = tracker.match_or_create_track(vehicle_bbox, 350.0)

    for index, plate in enumerate((
        "16R-105.17",
        "16R-105.17",
        "16R-105.17",
        "15R-105.17",
        "15R-105.17",
    )):
        tracker.update_track(
            track_id=track_id,
            vehicle_bbox=vehicle_bbox,
            plate_bbox=[880, 520, 930, 550],
            plate_text=plate,
            status="STRANGER",
            conf=0.96,
            now=350.0 + index * 0.2,
        )

    assert tracker.tracks[track_id].best_plate == "15R-105.17"


def test_one_clear_15_prefix_survives_repeated_interpolated_16_reads():
    tracker = PlateTracker()
    vehicle_bbox = [650, 80, 1100, 650]
    track_id = tracker.match_or_create_track(vehicle_bbox, 360.0)

    observations = [("15R-102.53", 0.99), *[("16R-102.53", 0.99)] * 6]
    for index, (plate, confidence) in enumerate(observations):
        tracker.update_track(
            track_id=track_id,
            vehicle_bbox=vehicle_bbox,
            plate_bbox=[880, 520, 930, 550],
            plate_text=plate,
            status="STRANGER",
            conf=confidence,
            now=360.0 + index * 0.2,
        )

    assert tracker.tracks[track_id].best_plate == "15R-102.53"


def test_one_clear_53_suffix_survives_repeated_interpolated_63_reads():
    tracker = PlateTracker()
    vehicle_bbox = [650, 80, 1100, 650]
    track_id = tracker.match_or_create_track(vehicle_bbox, 370.0)

    observations = [("15R-102.53", 0.99), *[("16R-102.63", 0.99)] * 6]
    for index, (plate, confidence) in enumerate(observations):
        tracker.update_track(
            track_id=track_id,
            vehicle_bbox=vehicle_bbox,
            plate_bbox=[880, 520, 930, 550],
            plate_text=plate,
            status="STRANGER",
            conf=confidence,
            now=370.0 + index * 0.2,
        )

    assert tracker.tracks[track_id].best_plate == "15R-102.53"


def test_character_consensus_resolves_106_to_105_with_repeated_five_evidence():
    tracker = PlateTracker()
    vehicle_bbox = [650, 80, 1100, 650]
    track_id = tracker.match_or_create_track(vehicle_bbox, 375.0)

    for index, plate in enumerate((
        "15R-106.17",
        "15R-106.17",
        "15R-106.17",
        "15R-105.17",
        "15R-105.17",
    )):
        tracker.update_track(
            track_id=track_id,
            vehicle_bbox=vehicle_bbox,
            plate_bbox=[880, 520, 930, 550],
            plate_text=plate,
            status="STRANGER",
            conf=0.96,
            now=375.0 + index * 0.2,
        )

    assert tracker.tracks[track_id].best_plate == "15R-105.17"


def test_character_consensus_resolves_trailer_h_to_m_with_material_m_evidence():
    tracker = PlateTracker()
    vehicle_bbox = [650, 80, 1100, 650]
    track_id = tracker.match_or_create_track(vehicle_bbox, 390.0)

    for index, (plate, confidence) in enumerate((
        ("15RH-071.97", 0.99),
        ("15RH-071.97", 0.98),
        ("15RH-071.97", 0.97),
        ("15RM-071.97", 0.94),
        ("15RM-071.97", 0.95),
    )):
        tracker.update_track(
            track_id=track_id,
            vehicle_bbox=vehicle_bbox,
            plate_bbox=[880, 520, 930, 560],
            plate_text=plate,
            status="STRANGER",
            conf=confidence,
            now=390.0 + index * 0.2,
        )

    assert tracker.tracks[track_id].best_plate == "15RM-071.97"


def test_verified_plate_canonicalization_only_corrects_close_variants():
    from detection.gate_pipeline import GatePipeline

    pipeline = GatePipeline.__new__(GatePipeline)
    pipeline._verified_plates = ["15R-105.17", "15R-102.53"]

    assert pipeline._canonicalize_verified_plate("16R-106.17") == "15R-105.17"
    assert pipeline._canonicalize_verified_plate("16R-102.63") == "15R-102.53"
    assert pipeline._canonicalize_verified_plate("29A-123.45") == "29A-123.45"


def test_vehicle_dedupe_keeps_two_real_trucks_but_collapses_nested_boxes():
    from detection.gate_pipeline import GatePipeline

    detections = [
        {"class": "truck", "bbox": [600, 80, 1200, 850], "zone_name": "Zone 1"},
        {"class": "truck", "bbox": [720, 180, 1160, 810], "zone_name": "Zone 1"},
        {"class": "truck", "bbox": [80, 220, 540, 760], "zone_name": "Zone 2"},
    ]

    deduped = GatePipeline._dedupe_vehicle_detections(detections)

    assert len(deduped) == 2
    assert [600, 80, 1200, 850] in [item["bbox"] for item in deduped]
    assert [80, 220, 540, 760] in [item["bbox"] for item in deduped]


def test_zone_fallback_scans_only_lane_whose_vehicle_detector_missed():
    from detection.gate_pipeline import GatePipeline

    pipeline = GatePipeline.__new__(GatePipeline)
    pipeline._active_zones = [
        {
            "name": "Zone 1",
            "polygon_points": [
                {"x": 0.50, "y": 0.45},
                {"x": 0.99, "y": 0.45},
                {"x": 0.99, "y": 0.99},
                {"x": 0.60, "y": 0.99},
            ],
        },
        {
            "name": "Zone 2",
            "polygon_points": [
                {"x": 0.01, "y": 0.45},
                {"x": 0.48, "y": 0.45},
                {"x": 0.36, "y": 0.99},
                {"x": 0.01, "y": 0.99},
            ],
        },
    ]

    fallbacks = pipeline._zone_fallback_detections(1600, 900, {"IN_2"})

    assert len(fallbacks) == 1
    assert fallbacks[0]["lane"] == "IN_1"
    assert fallbacks[0]["_zone_fallback"]
    assert fallbacks[0]["_force_stationary"]


def test_short_low_resolution_plate_finalizes_after_three_frames_and_leaves_view():
    tracker = PlateTracker()
    vehicle_bbox = [0, 250, 570, 680]
    track_id = tracker.match_or_create_track(vehicle_bbox, 400.0)

    for plate, confidence, variants, now in (
        ("15BM-592.99", 0.67, [{"plate": "15HM-5929", "confidence": 0.70}], 400.0),
        ("15HM-2298", 0.73, [{"plate": "15HM-229.88", "confidence": 0.69}], 400.2),
        ("15HM-0028", 0.75, [{"plate": "15HH-032.98", "confidence": 0.69}], 400.4),
    ):
        tracker.update_track(
            track_id=track_id,
            vehicle_bbox=vehicle_bbox,
            plate_bbox=[110, 560, 150, 595],
            plate_text=plate,
            status="STRANGER",
            conf=confidence,
            now=now,
            variants=variants,
        )

    track = tracker.tracks[track_id]
    assert not track.should_emit_event(400.4)
    assert track.best_plate == "15HH-032.98"
    assert track.should_emit_event(401.2)


def test_gate_schedules_stored_crop_when_plate_leaves_ocr_view():
    from detection.gate_pipeline import GatePipeline

    async def exercise():
        pipeline = GatePipeline.__new__(GatePipeline)
        pipeline.camera_id = "GATE-01"
        pipeline.tracker = PlateTracker()
        pipeline._recent_events = {}
        pipeline._cooldown_seconds = 20.0
        captured = []

        async def fake_handle(**kwargs):
            captured.append(kwargs)

        pipeline._handle_detected_plate = fake_handle
        vehicle_bbox = [650, 80, 1100, 650]
        track_id = pipeline.tracker.match_or_create_track(vehicle_bbox, 500.0)
        for now in (500.0, 500.3):
            track = pipeline.tracker.update_track(
                track_id=track_id,
                vehicle_bbox=vehicle_bbox,
                plate_bbox=[880, 520, 930, 550],
                plate_text="15R-102.53",
                status="STRANGER",
                conf=0.95,
                now=now,
            )
            track.latest_plate_crop = np.zeros((24, 48, 3), dtype=np.uint8)
            track.lane = "IN_1"
            track.zone_name = "Zone mới 1"

        pipeline._schedule_ready_track_events(501.1)
        await asyncio.sleep(0)

        assert len(captured) == 1
        assert captured[0]["plate"] == "15R-102.53"
        assert pipeline.tracker.tracks[track_id].event_emitted

    asyncio.run(exercise())


def test_fragmented_tracks_in_same_lane_passage_emit_only_one_event():
    from detection.gate_pipeline import GatePipeline

    async def exercise():
        pipeline = GatePipeline.__new__(GatePipeline)
        pipeline.camera_id = "GATE-01"
        pipeline.tracker = PlateTracker()
        pipeline._recent_events = {}
        pipeline._cooldown_seconds = 20.0
        pipeline._ai_busy = False
        pipeline._lane_passages = {}
        captured = []

        async def fake_handle(**kwargs):
            captured.append(kwargs)

        pipeline._handle_detected_plate = fake_handle
        for index, plate in enumerate(("15R-102.53", "16R-102.63")):
            track_id = f"V{index + 1:03d}"
            for now in (700.0, 700.3, 700.6):
                track = pipeline.tracker.update_track(
                    track_id=track_id,
                    vehicle_bbox=[650, 80, 1100, 650],
                    plate_bbox=[880, 520, 930, 550],
                    plate_text=plate,
                    status="STRANGER",
                    conf=0.99,
                    now=now,
                )
            track.latest_plate_crop = np.zeros((24, 48, 3), dtype=np.uint8)
            track.lane = "IN_1"
            track.zone_name = "Zone 1"
            track.passage_id = "P00001"

        aggregate = pipeline.tracker.tracks["V001"]
        for now in (700.0, 700.3, 700.6):
            aggregate.last_seen = now
            aggregate.last_plate_seen = now
            aggregate.add_plate_vote("16R-102.63", 0.99, now=now)
        pipeline._lane_passages = {
            "IN_1": {
                "id": "P00001",
                "last_seen": 700.6,
                "event_plate": "",
                "aggregate_track": aggregate,
                "crop": np.zeros((24, 48, 3), dtype=np.uint8),
                "lane": "IN_1",
                "zone_name": "Zone 1",
            }
        }

        pipeline._schedule_ready_passage_events(704.0)
        await asyncio.sleep(0)

        assert len(captured) == 1
        assert sum(track.event_emitted for track in pipeline.tracker.tracks.values()) == 2

    asyncio.run(exercise())


def test_overlapping_track_after_event_reuses_passage_and_frozen_best_plate():
    from detection.gate_pipeline import GatePipeline

    pipeline = GatePipeline.__new__(GatePipeline)
    pipeline.tracker = PlateTracker()
    pipeline._lane_passages = {}
    pipeline._next_passage_id = 2

    original = pipeline.tracker.update_track(
        "V001",
        [650, 330, 1590, 895],
        [1386, 721, 1442, 770],
        "15RM-032.98",
        "STRANGER",
        0.99,
        100.0,
    )
    original.lane = "IN_1"
    original.passage_id = "P00001"
    original.mark_event_emitted()
    passage = {
        "id": "P00001",
        "last_seen": 100.0,
        "event_plate": "15RM-032.98",
        "aggregate_track": original,
        "best_plate": "15RM-032.98",
        "best_confidence": 0.99,
        "last_vehicle_bbox": [650, 330, 1590, 895],
        "lane": "IN_1",
    }
    pipeline._lane_passages["V001"] = passage

    fragment = pipeline.tracker.update_track(
        "V002",
        [670, 340, 1580, 895],
        None,
        "",
        "SCANNING",
        0.0,
        102.0,
    )
    fragment.lane = "IN_1"

    reused = pipeline._touch_vehicle_passage("V002", "IN_1", 102.0, fragment)

    assert reused is passage
    assert fragment.event_emitted
    assert fragment.best_plate == "15RM-032.98"
    assert fragment.best_conf == 0.99


def test_receding_plate_variant_is_deduped_for_long_stationary_passage():
    from detection.gate_pipeline import GatePipeline

    pipeline = GatePipeline.__new__(GatePipeline)
    pipeline._recent_passage_results = [
        {
            "plate": "15RM03298",
            "confidence": 0.99,
            "lane": "IN_1",
            "timestamp": 100.0,
        }
    ]

    assert pipeline._is_recent_passage_variant("15RM-032.68", "IN_1", 190.0)
    assert not pipeline._is_recent_passage_variant("15R-158.45", "IN_1", 190.0)


def test_emitted_track_freezes_overlay_and_rejects_later_ocr_variants():
    tracker = PlateTracker()
    vehicle_bbox = [620, 120, 1080, 650]
    track_id = tracker.match_or_create_track(vehicle_bbox, 600.0)
    for now in (600.0, 600.3, 600.6):
        track = tracker.update_track(
            track_id=track_id,
            vehicle_bbox=vehicle_bbox,
            plate_bbox=[880, 520, 940, 555],
            plate_text="15R-105.17",
            status="STRANGER",
            conf=0.99,
            now=now,
        )

    track.mark_event_emitted()
    tracker.update_track(
        track_id=track_id,
        vehicle_bbox=vehicle_bbox,
        plate_bbox=[880, 520, 940, 555],
        plate_text="16R-106.17",
        status="STRANGER",
        conf=1.0,
        now=601.0,
    )

    detection = tracker.get_live_detections(601.0)[0]
    assert track.best_plate == "15R-105.17"
    assert detection["plate"] == "15R-105.17"
    assert detection["confidence"] == 0.99


def test_lane_fallback_plate_box_keeps_absolute_frame_coordinates():
    from detection.gate_pipeline import GatePipeline

    pipeline = GatePipeline.__new__(GatePipeline)
    pipeline.tracker = PlateTracker()
    observed_plate = [1410, 720, 1470, 765]
    zone_box = [650, 330, 1590, 895]
    yolo_vehicle_box = [900, 180, 1570, 880]

    resolved = pipeline._resolve_plate_box(
        observed_plate,
        zone_box,
        yolo_vehicle_box,
        zone_fallback=True,
    )

    assert resolved == observed_plate


def test_vehicle_dedupe_never_collapses_overlapping_vehicles_from_different_lanes():
    from detection.gate_pipeline import GatePipeline

    detections = [
        {"class": "truck", "bbox": [500, 120, 1200, 850], "lane": "IN_1"},
        {"class": "truck", "bbox": [420, 180, 1050, 820], "lane": "IN_2"},
    ]

    assert len(GatePipeline._dedupe_vehicle_detections(detections)) == 2


def test_vehicle_dedupe_preserves_two_partially_overlapping_trucks_in_same_lane():
    from detection.gate_pipeline import GatePipeline

    detections = [
        {"class": "truck", "bbox": [610, 180, 1120, 820], "lane": "IN_1"},
        {"class": "truck", "bbox": [850, 230, 1510, 880], "lane": "IN_1"},
    ]

    assert len(GatePipeline._dedupe_vehicle_detections(detections)) == 2


def test_batch_assignment_never_reuses_one_track_for_two_vehicles():
    tracker = PlateTracker()
    existing_id = tracker.match_or_create_track([600, 160, 1080, 820], 900.0)
    existing = tracker.update_track(
        track_id=existing_id,
        vehicle_bbox=[600, 160, 1080, 820],
        plate_bbox=None,
        plate_text="",
        status="SCANNING",
        conf=0.85,
        now=900.0,
    )
    existing.lane = "IN_1"

    assigned = tracker.match_detections(
        [
            {"bbox": [620, 170, 1100, 830], "lane": "IN_1"},
            {"bbox": [850, 220, 1510, 880], "lane": "IN_1"},
        ],
        900.1,
    )

    assert assigned[0] == existing_id
    assert len(set(assigned)) == 2


def test_track_matching_never_crosses_configured_lanes():
    tracker = PlateTracker()
    first_id = tracker.match_or_create_track([700, 160, 1320, 850], 901.0, lane="IN_1")
    first = tracker.update_track(
        first_id,
        [700, 160, 1320, 850],
        None,
        "",
        "SCANNING",
        0.85,
        901.0,
    )
    first.lane = "IN_1"

    adjacent_id = tracker.match_or_create_track(
        [720, 170, 1340, 860],
        901.1,
        lane="IN_2",
    )

    assert adjacent_id != first_id


def test_locked_plate_track_does_not_jump_to_centroid_only_neighbor():
    tracker = PlateTracker()
    first_id = tracker.match_or_create_track([700, 160, 1300, 850], 902.0, lane="IN_1")
    first = tracker.update_track(
        first_id,
        [700, 160, 1300, 850],
        [1160, 720, 1230, 765],
        "15R-105.17",
        "STRANGER",
        0.99,
        902.0,
    )
    first.lane = "IN_1"
    first.display_confirmed = True

    neighbor_id = tracker.match_or_create_track(
        [1050, 170, 1650, 860],
        902.2,
        lane="IN_1",
    )

    assert neighbor_id != first_id


def test_stale_track_is_not_reused_by_following_vehicle():
    tracker = PlateTracker()
    first_id = tracker.match_or_create_track([700, 160, 1300, 850], 903.0, lane="IN_1")
    first = tracker.update_track(
        first_id,
        [700, 160, 1300, 850],
        [1160, 720, 1230, 765],
        "15R-105.17",
        "STRANGER",
        0.99,
        903.0,
    )
    first.lane = "IN_1"

    following_id = tracker.match_or_create_track(
        [710, 165, 1310, 855],
        904.0,
        lane="IN_1",
    )

    assert following_id != first_id


def test_zone_scan_plate_is_attached_to_matching_physical_vehicle_track():
    tracker = PlateTracker()
    green_id = tracker.match_or_create_track([700, 180, 1510, 880], 905.0, lane="IN_1")
    green = tracker.update_track(
        green_id,
        [700, 180, 1510, 880],
        None,
        "",
        "SCANNING",
        0.85,
        905.0,
    )
    green.lane = "IN_1"
    adjacent_id = tracker.match_or_create_track([80, 260, 620, 820], 905.0, lane="IN_2")
    adjacent = tracker.update_track(
        adjacent_id,
        [80, 260, 620, 820],
        None,
        "",
        "SCANNING",
        0.85,
        905.0,
    )
    adjacent.lane = "IN_2"

    owner = tracker.find_vehicle_track_for_plate([1390, 720, 1450, 770], "IN_1", 905.1)

    assert owner == green_id


def test_physical_vehicle_bbox_wins_over_zone_fallback_for_same_passage():
    tracker = PlateTracker()
    passage_id = "P00021"
    fallback = tracker.update_track(
        "ZONE_FALLBACK:IN_1",
        [600, 120, 1590, 890],
        [1385, 720, 1445, 770],
        "15R-102.53",
        "STRANGER",
        1.0,
        906.0,
    )
    fallback.is_zone_fallback = True
    fallback.passage_id = passage_id
    fallback.display_confirmed = True

    physical = tracker.update_track(
        "V001",
        [720, 180, 1510, 880],
        [1388, 722, 1448, 772],
        "15R-102.53",
        "STRANGER",
        0.99,
        906.0,
    )
    physical.passage_id = passage_id
    physical.display_confirmed = True

    detections = tracker.get_live_detections(906.1, 0.50)

    assert len(detections) == 1
    assert detections[0]["track_id"] == "V001"


def test_rear_candidate_selection_ignores_plate_near_forward_axles():
    from detection.gate_pipeline import GatePipeline

    candidates = [
        {
            "plate": "15H-032.03",
            "bbox_in_crop": [120, 280, 190, 320],
            "score": 3.0,
            "confidence": 1.0,
        },
        {
            "plate": "15R-105.17",
            "bbox_in_crop": [410, 500, 475, 545],
            "score": 2.4,
            "confidence": 0.96,
        },
    ]

    selected = GatePipeline._select_rear_plate_candidate(candidates, 500, 600)

    assert selected is not None
    assert selected["plate"] == "15R-105.17"


def test_high_angle_rear_roi_is_opt_in_and_keeps_normal_camera_selection_unchanged():
    from detection.gate_pipeline import GatePipeline

    candidates = [
        {
            "plate": "15R-102.53",
            "bbox_in_crop": [180, 90, 260, 130],
            "source": "high_angle_far_rear_raw",
            "score": 2.6,
            "confidence": 0.98,
        }
    ]

    assert GatePipeline._select_rear_plate_candidate(candidates, 500, 700) is None
    selected = GatePipeline._select_rear_plate_candidate(candidates, 500, 700, high_angle=True)

    assert selected is not None
    assert selected["plate"] == "15R-102.53"
    assert GatePipeline._is_high_angle_vehicle([1000, 300, 1400, 900], 1600, 900)
    assert not GatePipeline._is_high_angle_vehicle([650, 330, 1590, 895], 1600, 900)


def test_each_vehicle_track_owns_a_separate_passage_in_the_same_lane():
    from detection.gate_pipeline import GatePipeline

    pipeline = GatePipeline.__new__(GatePipeline)
    pipeline._lane_passages = {}
    pipeline._next_passage_id = 1

    first = pipeline._touch_vehicle_passage("V001", "IN_1", 100.0)
    second = pipeline._touch_vehicle_passage("V002", "IN_1", 100.1)

    assert first["id"] != second["id"]
    assert len(pipeline._lane_passages) == 2


def test_short_overlapping_track_fragment_without_plate_reuses_passage():
    from detection.gate_pipeline import GatePipeline

    pipeline = GatePipeline.__new__(GatePipeline)
    pipeline._lane_passages = {}
    pipeline._next_passage_id = 1
    first_track = SimpleNamespace(best_plate="", vehicle_bbox=[700, 200, 1300, 880])
    second_track = SimpleNamespace(best_plate="", vehicle_bbox=[720, 210, 1320, 890])

    first = pipeline._touch_vehicle_passage("V001", "IN_1", 100.0, first_track)
    second = pipeline._touch_vehicle_passage("V002", "IN_1", 100.5, second_track)

    assert first["id"] == second["id"]


def test_lost_vehicle_bbox_expires_before_it_can_attach_to_the_next_vehicle():
    tracker = PlateTracker()
    track = tracker.update_track(
        track_id="V001",
        vehicle_bbox=[650, 200, 1200, 850],
        plate_bbox=[1000, 720, 1080, 770],
        plate_text="15R-105.17",
        status="STRANGER",
        conf=0.99,
        now=200.0,
    )
    track.bbox_confirmation_count = 2
    track.mark_event_emitted()

    assert tracker.get_live_detections(200.8)
    assert tracker.get_live_detections(201.3) == []


def test_ocr_priority_reserves_one_slot_for_each_lane():
    from detection.gate_pipeline import GatePipeline

    pipeline = GatePipeline.__new__(GatePipeline)
    pipeline.tracker = PlateTracker()
    pipeline._lane_fallback_last_ocr = {}
    detections = [
        {"bbox": [700, 100, 1500, 890], "lane": "IN_1", "_zone_fallback": True},
        {"bbox": [760, 160, 1450, 850], "lane": "IN_1", "_zone_fallback": True},
        {"bbox": [20, 250, 720, 890], "lane": "IN_2", "_zone_fallback": True},
    ]

    selected = pipeline._prioritize_ocr_detections(detections, now=900.0, limit=2)

    assert {item["lane"] for item in selected} == {"IN_1", "IN_2"}


def test_distant_bbox_cannot_replace_stable_plate_location_on_small_quality_gain():
    tracker = PlateTracker(smoothing_alpha=0.8)
    vehicle_bbox = [700, 100, 1550, 880]
    track_id = tracker.match_or_create_track(vehicle_bbox, 910.0)
    original_box = [1380, 700, 1450, 750]
    tracker.update_track(
        track_id=track_id,
        vehicle_bbox=vehicle_bbox,
        plate_bbox=original_box,
        plate_text="15R-105.17",
        status="STRANGER",
        conf=0.98,
        now=910.0,
        bbox_quality=2.50,
    )
    tracker.update_track(
        track_id=track_id,
        vehicle_bbox=vehicle_bbox,
        plate_bbox=[1320, 380, 1370, 440],
        plate_text="15R-105.17",
        status="STRANGER",
        conf=0.99,
        now=910.3,
        bbox_quality=2.55,
    )

    assert tracker.tracks[track_id].plate_bbox == original_box


def test_later_lower_rear_bbox_replaces_early_door_candidate():
    tracker = PlateTracker()
    vehicle_bbox = [650, 330, 1590, 895]
    track_id = tracker.match_or_create_track(vehicle_bbox, 912.0)
    tracker.update_track(
        track_id=track_id,
        vehicle_bbox=vehicle_bbox,
        plate_bbox=[1394, 511, 1453, 563],
        plate_text="15RM-097.87",
        status="STRANGER",
        conf=1.0,
        now=912.0,
        bbox_quality=2.12,
    )
    tracker.update_track(
        track_id=track_id,
        vehicle_bbox=vehicle_bbox,
        plate_bbox=[1386, 721, 1442, 770],
        plate_text="15RM-097.87",
        status="STRANGER",
        conf=1.0,
        now=912.3,
        bbox_quality=2.16,
    )
    tracker.update_track(
        track_id=track_id,
        vehicle_bbox=vehicle_bbox,
        plate_bbox=[1384, 720, 1441, 770],
        plate_text="15RM-097.87",
        status="STRANGER",
        conf=1.0,
        now=912.6,
        bbox_quality=2.17,
    )

    assert compute_iou(tracker.tracks[track_id].plate_bbox, [1386, 721, 1442, 770]) >= 0.90


def test_vertical_door_latch_bbox_is_never_published_as_a_plate():
    tracker = PlateTracker()
    vehicle_bbox = [650, 330, 1590, 895]
    track_id = tracker.match_or_create_track(vehicle_bbox, 913.0)

    for now in (913.0, 913.4, 913.8):
        tracker.update_track(
            track_id=track_id,
            vehicle_bbox=vehicle_bbox,
            plate_bbox=[1400, 480, 1424, 540],
            plate_text="15R-105.17",
            status="STRANGER",
            conf=0.99,
            now=now,
        )

    assert tracker.tracks[track_id].plate_bbox is None
    assert tracker.get_live_detections(914.8) == []


def test_configured_fifty_percent_threshold_keeps_best_fifty_one_percent_result():
    tracker = PlateTracker()
    vehicle_bbox = [650, 330, 1590, 895]
    track_id = tracker.match_or_create_track(vehicle_bbox, 914.0)

    for now, confidence in ((914.0, 0.50), (914.4, 0.51), (914.8, 0.49)):
        tracker.update_track(
            track_id=track_id,
            vehicle_bbox=vehicle_bbox,
            plate_bbox=[1386, 721, 1442, 770],
            plate_text="15R-102.53",
            status="STRANGER",
            conf=confidence,
            now=now,
        )

    track = tracker.tracks[track_id]
    assert track.best_conf == 0.51
    track.last_vehicle_seen = 915.2
    assert tracker.get_live_detections(915.6, min_confidence=0.50)[0]["confidence"] == 0.51
    assert tracker.get_live_detections(915.6, min_confidence=0.52) == []


def test_single_fast_vehicle_read_above_user_threshold_is_finalized_after_passage():
    from detection.gate_pipeline import GatePipeline

    async def exercise():
        pipeline = GatePipeline.__new__(GatePipeline)
        pipeline.camera_id = "GATE-01"
        pipeline.tracker = PlateTracker()
        pipeline._ai_busy = False
        pipeline.min_confidence = 0.50
        captured = []

        async def fake_handle(**kwargs):
            captured.append(kwargs)

        pipeline._handle_detected_plate = fake_handle
        track = pipeline.tracker.update_track(
            track_id="V001",
            vehicle_bbox=[650, 330, 1590, 895],
            plate_bbox=[1386, 721, 1442, 770],
            plate_text="15RM-032.88",
            status="STRANGER",
            conf=0.51,
            now=916.0,
        )
        track.passage_id = "P00010"
        pipeline._lane_passages = {
            "IN_1": {
                "id": "P00010",
                "last_seen": 916.0,
                "event_plate": "",
                "aggregate_track": track,
                "crop": np.zeros((24, 48, 3), dtype=np.uint8),
                "lane": "IN_1",
                "zone_name": "Zone 1",
            }
        }

        pipeline._schedule_ready_passage_events(920.0)
        await asyncio.sleep(0)

        assert len(captured) == 1
        assert captured[0]["plate"] == "15RM-032.88"
        assert captured[0]["confidence"] == 0.51

    asyncio.run(exercise())


def test_vehicle_status_uses_registered_vehicle_setting_only():
    from detection.gate_pipeline import GatePipeline

    pipeline = GatePipeline.__new__(GatePipeline)
    pipeline._registered_vehicle_statuses = {
        pipeline._compact_plate("15R-105.17"): "STRANGER",
        pipeline._compact_plate("29A-123.45"): "KNOWN",
    }

    assert pipeline.resolve_vehicle_status("15R-105.17") == "STRANGER"
    assert pipeline.resolve_vehicle_status("29A-123.45") == "KNOWN"
    assert pipeline.resolve_vehicle_status("15R-999.99") == "STRANGER"


def test_lower_confidence_variant_cannot_replace_published_live_plate():
    tracker = PlateTracker()
    vehicle_bbox = [650, 330, 1590, 895]
    for index, now in enumerate((921.0, 921.4, 921.8)):
        tracker.update_track(
            track_id="V001",
            vehicle_bbox=vehicle_bbox,
            plate_bbox=[1386, 721, 1442, 770],
            plate_text="15RM-032.88",
            status="STRANGER",
            conf=1.0,
            now=now,
        )

    assert tracker.get_live_detections(922.0, 0.50)[0]["plate"] == "15RM-032.88"

    for index, now in enumerate((922.2, 922.6, 923.0)):
        track = tracker.update_track(
            track_id="V001",
            vehicle_bbox=vehicle_bbox,
            plate_bbox=[1386, 721, 1442, 770],
            plate_text="15RM-032.58",
            status="STRANGER",
            conf=0.93,
            now=now,
        )
        track.last_vehicle_seen = now

    assert tracker.get_live_detections(923.2, 0.50)[0]["plate"] == "15RM-032.88"


def test_fragmented_tracks_in_one_passage_publish_only_best_confirmed_bbox():
    tracker = PlateTracker()
    vehicle_bbox = [650, 330, 1590, 895]
    boxes = {
        "V001": ([1386, 721, 1442, 770], 2.10),
        "V002": ([1390, 724, 1448, 772], 2.40),
    }
    for track_id, (plate_box, quality) in boxes.items():
        for now in (924.0, 924.4, 924.8):
            track = tracker.update_track(
                track_id=track_id,
                vehicle_bbox=vehicle_bbox,
                plate_bbox=plate_box,
                plate_text="15R-105.17",
                status="STRANGER",
                conf=0.99,
                now=now,
                bbox_quality=quality,
            )
            track.passage_id = "P00011"

    detections = tracker.get_live_detections(925.0, 0.50)

    assert len(detections) == 1
    assert compute_iou(detections[0]["bbox"], boxes["V002"][0]) >= 0.95


def test_first_valid_plate_observation_publishes_unlabeled_bbox_immediately():
    tracker = PlateTracker()
    track = tracker.update_track(
        "V001",
        [650, 330, 1590, 895],
        [1386, 721, 1442, 770],
        "15R-102.53",
        "STRANGER",
        0.91,
        930.0,
    )
    track.lane = "IN_1"

    detections = tracker.get_live_detections(930.1, 0.95)

    assert len(detections) == 1
    assert detections[0]["bbox"] == [1386, 721, 1442, 770]
    assert detections[0]["plate"] == ""
    assert detections[0]["lpr_status"] == "SCANNING"
    assert not detections[0]["is_locked"]


def test_vehicle_motion_translation_preserves_plate_bbox_size_and_aspect():
    tracker = PlateTracker()
    track_id = tracker.match_or_create_track([800, 180, 1500, 850], 915.0)
    tracker.update_track(
        track_id=track_id,
        vehicle_bbox=[800, 180, 1500, 850],
        plate_bbox=[1380, 700, 1450, 750],
        plate_text="15RM-097.87",
        status="STRANGER",
        conf=0.98,
        now=915.0,
    )

    tracker.update_related_plate_tracks(track_id, [760, 100, 1560, 890], 915.2)
    moved = tracker.tracks[track_id].plate_bbox

    assert moved is not None
    assert moved[2] - moved[0] == 70
    assert moved[3] - moved[1] == 50


def test_zone_fallback_bbox_stays_absolute_between_ocr_passes():
    tracker = PlateTracker()
    track_id = tracker.match_or_create_track([650, 330, 1590, 895], 917.0)
    track = tracker.update_track(
        track_id=track_id,
        vehicle_bbox=[650, 330, 1590, 895],
        plate_bbox=[1386, 721, 1442, 770],
        plate_text="15RM-097.87",
        status="STRANGER",
        conf=1.0,
        now=917.0,
    )
    track.is_zone_fallback = True

    tracker.update_related_plate_tracks(track_id, [900, 120, 1580, 890], 917.2)

    assert track.plate_bbox == [1386, 721, 1442, 770]


def test_passage_below_configured_confidence_is_logged_as_unknown():
    from detection.gate_pipeline import GatePipeline

    async def exercise():
        pipeline = GatePipeline.__new__(GatePipeline)
        pipeline.camera_id = "GATE-01"
        pipeline.tracker = PlateTracker()
        pipeline._ai_busy = False
        pipeline.min_confidence = 0.90
        captured = []

        async def fake_handle(**kwargs):
            captured.append(kwargs)

        pipeline._handle_detected_plate = fake_handle
        track_id = pipeline.tracker.match_or_create_track([700, 100, 1500, 880], 920.0)
        for now in (920.0, 920.3, 920.6):
            track = pipeline.tracker.update_track(
                track_id=track_id,
                vehicle_bbox=[700, 100, 1500, 880],
                plate_bbox=[1380, 700, 1450, 750],
                plate_text="15R-158.45",
                status="STRANGER",
                conf=0.85,
                now=now,
            )
        track.passage_id = "P00009"
        pipeline._lane_passages = {
            "IN_1": {
                "id": "P00009",
                "last_seen": 920.6,
                "event_plate": "",
                "aggregate_track": track,
                "crop": np.zeros((24, 48, 3), dtype=np.uint8),
                "lane": "IN_1",
                "zone_name": "Zone 1",
            }
        }

        pipeline._schedule_ready_passage_events(924.0)
        await asyncio.sleep(0)

        assert len(captured) == 1
        assert captured[0]["plate"] == "UNKNOWN"
        assert captured[0]["confidence"] == 0.0
        assert pipeline._lane_passages["IN_1"]["event_plate"] == "UNKNOWN"

    asyncio.run(exercise())


def test_confirmed_vehicle_without_plate_bbox_is_not_logged_as_unknown():
    from detection.gate_pipeline import GatePipeline

    async def exercise():
        pipeline = GatePipeline.__new__(GatePipeline)
        pipeline.camera_id = "GATE-01"
        pipeline.tracker = PlateTracker()
        pipeline._ai_busy = False
        pipeline.min_confidence = 0.70
        captured = []

        async def fake_handle(**kwargs):
            captured.append(kwargs)

        pipeline._handle_detected_plate = fake_handle
        pipeline._lane_passages = {
            "V001": {
                "id": "P00010",
                "last_seen": 930.0,
                "first_vehicle_seen": 929.0,
                "vehicle_observations": 5,
                "event_plate": "",
                "aggregate_track": None,
                "vehicle_crop": np.zeros((80, 160, 3), dtype=np.uint8),
                "lane": "IN_1",
                "zone_name": "Zone 1",
                "video_timecode": "04:20",
            }
        }

        pipeline._schedule_ready_passage_events(934.0)
        pipeline._schedule_ready_passage_events(935.0)
        await asyncio.sleep(0)

        assert captured == []
        assert pipeline._lane_passages["V001"]["filtered"] is True

    asyncio.run(exercise())


def test_passage_keeps_highest_confidence_read_when_later_frames_are_noisy():
    from detection.gate_pipeline import GatePipeline

    async def exercise():
        pipeline = GatePipeline.__new__(GatePipeline)
        pipeline.camera_id = "GATE-01"
        pipeline.tracker = PlateTracker()
        pipeline._ai_busy = False
        pipeline.min_confidence = 0.50
        pipeline._recent_events = {}
        captured = []

        async def fake_handle(**kwargs):
            captured.append(kwargs)

        pipeline._handle_detected_plate = fake_handle
        track = pipeline.tracker.update_track(
            track_id="V001",
            vehicle_bbox=[650, 330, 1590, 895],
            plate_bbox=[1386, 721, 1442, 770],
            plate_text="15RM-032.68",
            status="STRANGER",
            conf=0.90,
            now=950.0,
        )
        track.passage_id = "P00012"
        pipeline._lane_passages = {
            "V001": {
                "id": "P00012",
                "last_seen": 950.0,
                "event_plate": "",
                "aggregate_track": track,
                "crop": np.zeros((24, 48, 3), dtype=np.uint8),
                "best_plate": "15RM-032.98",
                "best_confidence": 0.99,
                "lane": "IN_2",
                "zone_name": "Zone mới 2",
                "video_timecode": "03:50",
            }
        }

        pipeline._schedule_ready_passage_events(954.0)
        await asyncio.sleep(0)

        assert len(captured) == 1
        assert captured[0]["plate"] == "15RM-032.98"
        assert captured[0]["confidence"] == 0.99
        assert captured[0]["zone_name"] == "Zone mới 2"
        assert captured[0]["video_timecode"] == "03:50"

    asyncio.run(exercise())


def test_min_confidence_config_persists_across_pipeline_instances(tmp_path):
    from detection.gate_pipeline import GatePipeline

    config_path = tmp_path / "gate_pipeline.json"
    first = GatePipeline.__new__(GatePipeline)
    first.camera_id = "GATE-01"
    first._config_path = config_path
    assert first.update_min_confidence(0.83) == 0.83

    second = GatePipeline.__new__(GatePipeline)
    second.camera_id = "GATE-01"
    second._config_path = config_path
    assert second._load_min_confidence(0.70) == 0.83


def test_confirmed_bbox_stays_visible_between_ocr_cycles_while_vehicle_is_tracked():
    tracker = PlateTracker()
    vehicle_box = [650, 330, 1590, 895]
    for now in (1000.0, 1000.4):
        tracker.update_track(
            track_id="V001",
            vehicle_bbox=vehicle_box,
            plate_bbox=[1386, 721, 1442, 770],
            plate_text="15RM-032.98",
            status="STRANGER",
            conf=0.99,
            now=now,
        )

    assert tracker.get_live_detections(1000.5, 0.50)
    tracker.update_track(
        track_id="V001",
        vehicle_bbox=[645, 325, 1585, 890],
        plate_bbox=None,
        plate_text="",
        status="SCANNING",
        conf=0.85,
        now=1002.0,
    )

    detections = tracker.get_live_detections(1002.0, 0.50)
    assert len(detections) == 1
    assert detections[0]["plate"] == "15RM-032.98"


def test_single_near_certain_read_displays_bbox_immediately_for_fast_vehicle():
    tracker = PlateTracker()
    tracker.update_track(
        track_id="V001",
        vehicle_bbox=[650, 330, 1590, 895],
        plate_bbox=[1386, 721, 1442, 770],
        plate_text="15R-102.53",
        status="STRANGER",
        conf=0.99,
        now=1005.0,
    )

    detections = tracker.get_live_detections(1005.0, 0.50)
    assert len(detections) == 1
    assert detections[0]["plate"] == "15R-102.53"


def test_video_timecode_prefers_seekable_playback_position_and_never_regresses_to_zero():
    from detection.gate_pipeline import GatePipeline

    class Reader:
        position_ms = 268_000

        def get_playback_status(self):
            return {"seekable": True, "positionMs": self.position_ms, "durationMs": 1_000_000}

        def get_timecode(self):
            return "00:00"

    pipeline = GatePipeline.__new__(GatePipeline)
    pipeline.reader = Reader()
    pipeline._last_video_timecode = "00:00"
    assert pipeline._get_video_timecode() == "04:28"

    pipeline.reader.position_ms = 0
    assert pipeline._get_video_timecode() == "04:28"


def test_low_confidence_localizer_restores_detector_threshold_and_returns_rear_plate_box():
    import threading

    core = SimpleNamespace(conf_thresh=0.25)

    class Detector:
        detector = core

        def predict(self, image):
            assert self.detector.conf_thresh == 0.15
            return [
                SimpleNamespace(
                    confidence=0.18,
                    bounding_box=SimpleNamespace(x1=118, y1=422, x2=189, y2=473),
                )
            ]

    reader = LicensePlateReader.__new__(LicensePlateReader)
    reader._alpr = SimpleNamespace(detector=Detector())
    reader._lock = threading.Lock()

    localized = reader.localize_unread_plate_region(np.zeros((522, 713, 3), dtype=np.uint8))

    assert localized == {
        "bbox_in_crop": [118, 422, 189, 473],
        "detector_confidence": 0.18,
    }
    assert core.conf_thresh == 0.25


def test_low_confidence_plate_localization_needs_stable_nonblank_crop_before_unknown():
    from detection.gate_pipeline import GatePipeline

    class Reader:
        def scan_plate_from_frame_or_vehicle(self, *args, **kwargs):
            return []

        def localize_unread_plate_region(self, crop):
            return {
                "bbox_in_crop": [120, 420, 190, 470],
                "detector_confidence": 0.18,
            }

    pipeline = GatePipeline.__new__(GatePipeline)
    pipeline.camera_id = "GATE-01"
    pipeline.tracker = PlateTracker()
    pipeline.lpr_reader = Reader()
    pipeline._active_zones = []
    pipeline._lane_passages = {}
    pipeline._next_passage_id = 1
    pipeline._tracking_generation = 0
    pipeline._verified_plates = []

    vehicle_box = [0, 300, 720, 850]
    track = pipeline.tracker.update_track(
        "V001",
        vehicle_box,
        None,
        "",
        "SCANNING",
        0.85,
        100.0,
    )
    track.lane = "IN_1"
    frame = np.zeros((900, 1600, 3), dtype=np.uint8)
    textured = np.indices((50, 70)).sum(axis=0) % 2
    frame[720:770, 120:190] = (textured[..., None] * 180 + 35).astype(np.uint8)
    detection = {
            "class": "truck",
            "bbox": vehicle_box,
            "lane": "IN_1",
            "zone_name": "Zone 1",
            "_track_id": "V001",
            "_video_timecode": "10:19",
        }
    pipeline._sync_plate_detection(frame, [detection], 100.0, generation=0)

    passage = pipeline._lane_passages["V001"]
    assert passage["aggregate_track"] is None
    assert passage["crop"] is None
    assert not passage.get("localized_unread_only", False)

    pipeline._sync_plate_detection(frame, [detection], 100.5, generation=0)
    passage = pipeline._lane_passages["V001"]
    assert passage["crop"].shape == (54, 74, 3)
    assert passage["video_timecode"] == "10:19"
    assert passage["localized_unread_only"]
    assert passage["unread_support"] == 2
    assert pipeline.tracker.tracks["V001"].best_plate == ""


def test_confirmed_zone_fallback_bbox_bridges_ocr_cycles_but_still_expires():
    tracker = PlateTracker()
    track = tracker.update_track(
        "ZONE_FALLBACK:IN_1",
        [600, 120, 1590, 890],
        [1385, 720, 1445, 770],
        "15R-102.53",
        "STRANGER",
        1.0,
        200.0,
    )
    track.is_zone_fallback = True
    track.display_confirmed = True

    assert tracker.get_live_detections(202.3, 0.50)
    assert tracker.get_live_detections(202.5, 0.50) == []


def test_localized_unread_passage_without_valid_ocr_is_filtered_not_unknown():
    from detection.gate_pipeline import GatePipeline

    async def exercise():
        pipeline = GatePipeline.__new__(GatePipeline)
        pipeline.camera_id = "GATE-01"
        pipeline.tracker = PlateTracker()
        pipeline._ai_busy = False
        pipeline.min_confidence = 0.50
        captured = []

        async def fake_handle(**kwargs):
            captured.append(kwargs)

        pipeline._handle_detected_plate = fake_handle
        pipeline._lane_passages = {
            "V001": {
                "id": "P00030",
                "last_seen": 300.0,
                "first_vehicle_seen": 298.0,
                "vehicle_observations": 8,
                "event_plate": "",
                "aggregate_track": None,
                "crop": np.zeros((24, 48, 3), dtype=np.uint8),
                "localized_unread_only": True,
                "unread_support": 2,
                "lane": "IN_1",
                "zone_name": "Zone 1",
            }
        }
        pipeline._lane_last_activity = {"IN_1": 307.0}

        pipeline._schedule_ready_passage_events(308.0)
        await asyncio.sleep(0)
        assert captured == []

        live = pipeline.tracker.update_track(
            "V002",
            [650, 330, 1590, 895],
            [1386, 721, 1442, 770],
            "15R-102.53",
            "STRANGER",
            0.99,
            313.0,
        )
        live.lane = "IN_1"
        pipeline._lane_last_activity["IN_1"] = 313.0
        pipeline._schedule_ready_passage_events(313.0)
        await asyncio.sleep(0)
        assert captured == []

        pipeline.tracker.tracks.clear()
        pipeline._schedule_ready_passage_events(316.0)
        await asyncio.sleep(0)
        assert captured == []
        assert pipeline._lane_passages["V001"]["filtered"] is True

    asyncio.run(exercise())


def test_localized_low_detector_crop_runs_tight_ocr_with_normal_validation_threshold():
    import threading

    class OcrEngine:
        def predict(self, image):
            return SimpleNamespace(text="15RM03288", confidence=[0.96] * 9)

    reader = LicensePlateReader.__new__(LicensePlateReader)
    reader._alpr = SimpleNamespace(ocr=OcrEngine())
    reader._alternate_ocr = None
    reader._lock = threading.Lock()

    result = reader.recognize_localized_plate_region(
        np.full((520, 700, 3), 100, dtype=np.uint8),
        {"bbox_in_crop": [130, 410, 205, 465], "detector_confidence": 0.18},
    )

    assert result is not None
    assert result["plate"] == "15RM-032.88"
    assert result["confidence"] == 0.96
    assert result["bbox_in_crop"] == [130, 410, 205, 465]


def test_visual_plate_tracking_keeps_stationary_verified_bbox_and_drops_on_quality_loss():
    import cv2

    rng = np.random.default_rng(42)
    gray = rng.integers(20, 235, size=(320, 420), dtype=np.uint8)
    frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    tracker = PlateTracker()
    track = tracker.update_track(
        "V001",
        [50, 40, 380, 300],
        [230, 215, 310, 252],
        "15R-102.53",
        "STRANGER",
        0.99,
        100.0,
    )
    track.lane = "IN_1"
    assert tracker.get_live_detections(100.0, 0.50)

    tracker.update_visual_tracks(frame, 100.1)
    for index in range(1, 121):
        current_time = 100.1 + index * 0.1
        track.last_seen = current_time
        track.last_vehicle_seen = current_time
        tracker.update_visual_tracks(frame, current_time)

    detections = tracker.get_live_detections(112.2, 0.50)
    assert len(detections) == 1
    assert compute_iou(detections[0]["bbox"], [230, 215, 310, 252]) >= 0.90
    assert tracker.get_visual_active_lanes(112.2) == {"IN_1"}

    blank = np.zeros_like(frame)
    tracker.update_visual_tracks(blank, 112.3)
    assert tracker.get_live_detections(113.4, 0.50) == []


def test_visual_plate_tracking_moves_bbox_with_same_local_texture():
    import cv2

    rng = np.random.default_rng(7)
    gray = rng.integers(10, 245, size=(320, 420), dtype=np.uint8)
    frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    tracker = PlateTracker()
    track = tracker.update_track(
        "V001",
        [50, 40, 380, 300],
        [220, 210, 300, 247],
        "15R-105.17",
        "STRANGER",
        0.99,
        200.0,
    )
    tracker.get_live_detections(200.0, 0.50)
    tracker.update_visual_tracks(frame, 200.1)

    matrix = np.float32([[1.0, 0.0, 5.0], [0.0, 1.0, 3.0]])
    moved = cv2.warpAffine(frame, matrix, (frame.shape[1], frame.shape[0]))
    tracker.update_visual_tracks(moved, 200.2)
    detection = tracker.get_live_detections(200.2, 0.50)[0]

    assert abs(detection["bbox"][0] - 225) <= 3
    assert abs(detection["bbox"][1] - 213) <= 3
    assert detection["bbox"][2] - detection["bbox"][0] == 80
    assert detection["bbox"][3] - detection["bbox"][1] == 37


def test_provisional_plate_bbox_is_live_only_while_parent_vehicle_is_visible():
    tracker = PlateTracker()
    track = tracker.update_track(
        "V001",
        [50, 40, 380, 300],
        None,
        "",
        "SCANNING",
        0.85,
        300.0,
    )
    tracker.update_provisional_plate_box(track, [220, 210, 300, 247], 300.0)

    detection = tracker.get_live_detections(300.1, 0.95)[0]
    assert detection["plate"] == ""
    assert detection["bbox"] == [220, 210, 300, 247]
    assert not detection["is_locked"]

    assert tracker.get_live_detections(301.1, 0.95) == []


def test_visual_plate_bbox_drops_when_parent_vehicle_disappears():
    import cv2

    rng = np.random.default_rng(11)
    frame = cv2.cvtColor(
        rng.integers(10, 245, size=(320, 420), dtype=np.uint8),
        cv2.COLOR_GRAY2BGR,
    )
    tracker = PlateTracker()
    track = tracker.update_track(
        "V001",
        [50, 40, 380, 300],
        [220, 210, 300, 247],
        "15R-105.17",
        "KNOWN",
        0.99,
        400.0,
    )
    tracker.get_live_detections(400.0, 0.50)
    tracker.update_visual_tracks(frame, 400.1)
    assert tracker.get_live_detections(400.1, 0.50)

    tracker.update_visual_tracks(frame, 401.1)
    assert tracker.get_live_detections(401.1, 0.50) == []


def test_late_ocr_result_does_not_resurrect_bbox_after_vehicle_left():
    tracker = PlateTracker()
    tracker.update_track(
        "V001",
        [50, 40, 380, 300],
        None,
        "",
        "SCANNING",
        0.85,
        500.0,
    )
    tracker.update_track(
        "V001",
        [50, 40, 380, 300],
        [220, 210, 300, 247],
        "15R-105.17",
        "KNOWN",
        0.99,
        503.0,
    )

    assert tracker.get_live_detections(503.0, 0.50) == []


def test_lower_two_line_geometry_can_publish_provisional_bbox_before_ocr():
    from detection.gate_pipeline import GatePipeline

    class Reader:
        def localize_unread_plate_regions(self, crop, min_center_y=0.45):
            return [
                {
                    "bbox_in_crop": [300, 80, 348, 136],
                    "source": "recessed_plate_geometry",
                },
                {
                    "bbox_in_crop": [580, 220, 636, 280],
                    "source": "recessed_plate_geometry",
                },
            ]

        def recognize_localized_plate_region(self, crop, region):
            return None

    pipeline = GatePipeline.__new__(GatePipeline)
    pipeline.lpr_reader = Reader()
    published = []

    pipeline._recover_localized_candidate(
        np.zeros((400, 780, 3), dtype=np.uint8),
        allow_geometry=True,
        on_localized=published.append,
    )

    assert [item["bbox_in_crop"] for item in published] == [[580, 220, 636, 280]]

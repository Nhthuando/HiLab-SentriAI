"""
tests/test_db.py — Comprehensive Test & Verification Suite for Python asyncpg DB Module

Tests connection pooling, jsonb serialization/deserialization, and all 5 domain tables:
1. registered_vehicles
2. gate_events
3. zones
4. zone_violations
5. object_labels
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

# Ensure python-worker directory is on sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from db import (
    check_db_health,
    close_zone_violation,
    close_db_pool,
    count_stranger_vehicles,
    create_gate_event,
    create_object_label,
    create_zone,
    create_zone_violation,
    get_active_zones_by_camera,
    get_all_active_zones,
    get_all_object_labels,
    get_all_registered_plates,
    get_database_url,
    get_db_connection,
    get_gate_events_by_plate,
    get_open_violations,
    get_recent_gate_events,
    get_recent_zone_violations,
    get_vehicle_status_by_plate,
    init_db_pool,
    register_vehicle,
)


async def run_tests():
    print("=" * 70)
    print("SentriAI - FDN-PYTHON-DB Verification Test Suite")
    print("=" * 70)

    # 1. Test Database URL & Pool Initialization
    print("\n[1/7] Initializing asyncpg connection pool...")
    url = get_database_url()
    assert url, "Database URL must be present"
    print(f"  [OK] Database URL loaded successfully (length: {len(url)})")

    pool = await init_db_pool(min_size=1, max_size=5)
    assert pool is not None, "Pool must be initialized"
    print("  [OK] Pool created successfully")

    is_healthy = await check_db_health()
    assert is_healthy is True, "Database health check must return True"
    print("  [OK] check_db_health() returned True")

    # Generate unique test suffix to ensure idempotence
    test_run_id = uuid.uuid4().hex[:6].upper()
    test_plate = f"TEST-{test_run_id}"
    test_label_name = f"Nhan Test {test_run_id}"
    test_zone_name = f"Zone Test {test_run_id}"

    created_records = {
        "vehicles": [],
        "events": [],
        "violations": [],
        "zones": [],
        "labels": [],
    }

    try:
        # 2. Test registered_vehicles (AP-01)
        print("\n[2/7] Testing registered_vehicles (AP-01)...")
        status_before = await get_vehicle_status_by_plate(test_plate)
        assert status_before is None, "Non-existent vehicle must return None"
        print(f"  [OK] get_vehicle_status_by_plate('{test_plate}') returned None")

        new_veh = await register_vehicle(test_plate, status="KNOWN", note="Xe test tu dong")
        assert new_veh["plate_number"] == test_plate
        assert new_veh["status"] == "KNOWN"
        created_records["vehicles"].append(new_veh["id"])
        print(f"  [OK] register_vehicle('{test_plate}') created ID: {new_veh['id']}")

        status_after = await get_vehicle_status_by_plate(test_plate.lower())
        assert status_after == "KNOWN", "Vehicle lookup should match case-insensitively"
        print(f"  [OK] get_vehicle_status_by_plate('{test_plate.lower()}') returned 'KNOWN'")

        all_plates = await get_all_registered_plates()
        assert test_plate in all_plates
        assert all_plates[test_plate] == "KNOWN"
        print(f"  [OK] get_all_registered_plates() contains '{test_plate}' (total: {len(all_plates)})")

        # 3. Test gate_events (AP-02, AP-03, AP-04)
        print("\n[3/7] Testing gate_events (AP-02, AP-03, AP-04)...")
        event = await create_gate_event(
            camera_id="GATE-01",
            lane="IN_1",
            license_plate=test_plate,
            status="KNOWN",
            confidence=0.965,
            crop_path=f"data/crops/{test_plate}.jpg",
            clip_path=f"data/clips/{test_plate}.mp4",
        )
        assert event["id"] is not None
        assert event["license_plate"] == test_plate
        assert abs(event["confidence"] - 0.965) < 1e-4
        assert event["lane"] == "IN_1"
        created_records["events"].append(event["id"])
        print(f"  [OK] create_gate_event() created ID: {event['id']}")

        recent_events = await get_recent_gate_events(limit=5)
        assert any(e["id"] == event["id"] for e in recent_events), "Recent events must contain new event"
        print(f"  [OK] get_recent_gate_events() returned {len(recent_events)} events, includes test event")

        plate_events = await get_gate_events_by_plate(test_plate)
        assert len(plate_events) >= 1
        assert plate_events[0]["id"] == event["id"]
        print(f"  [OK] get_gate_events_by_plate('{test_plate}') matched {len(plate_events)} record(s)")

        strangers_count = await count_stranger_vehicles(
            start_time=datetime(2020, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )
        assert isinstance(strangers_count, int)
        print(f"  [OK] count_stranger_vehicles() returned: {strangers_count}")

        # 4. Test object_labels (M3)
        print("\n[4/7] Testing object_labels (M3)...")
        label = await create_object_label(vietnamese_name=test_label_name, base_class="forklift")
        assert label["id"] is not None
        assert label["vietnamese_name"] == test_label_name
        assert label["base_class"] == "forklift"
        created_records["labels"].append(label["id"])
        print(f"  [OK] create_object_label('{test_label_name}') created ID: {label['id']}")

        all_labels = await get_all_object_labels()
        assert any(l["id"] == label["id"] for l in all_labels)
        print(f"  [OK] get_all_object_labels() returned {len(all_labels)} label(s), includes test label")

        # 5. Test zones (AP-05, M2, M3)
        print("\n[5/7] Testing zones (AP-05)...")
        polygon = [{"x": 0.1, "y": 0.1}, {"x": 0.8, "y": 0.1}, {"x": 0.8, "y": 0.8}, {"x": 0.1, "y": 0.8}]
        targets = [test_label_name, "Xe máy"]
        zone = await create_zone(
            camera_id="BAI-KIEM",
            name=test_zone_name,
            polygon_points=polygon,
            rule_type="PROHIBIT_SPECIFIED",
            target_labels=targets,
            is_active=True,
        )
        assert zone["id"] is not None
        assert zone["name"] == test_zone_name
        assert zone["polygon_points"] == polygon, "JSONB polygon_points must deserialize to exact list of dicts"
        assert zone["target_labels"] == targets, "JSONB target_labels must deserialize to exact list"
        created_records["zones"].append(zone["id"])
        print(f"  [OK] create_zone('{test_zone_name}') created ID: {zone['id']}")

        camera_zones = await get_active_zones_by_camera("BAI-KIEM")
        assert any(z["id"] == zone["id"] for z in camera_zones)
        print(f"  [OK] get_active_zones_by_camera('BAI-KIEM') returned {len(camera_zones)} active zone(s)")

        all_active_zones = await get_all_active_zones()
        assert any(z["id"] == zone["id"] for z in all_active_zones)
        print(f"  [OK] get_all_active_zones() returned {len(all_active_zones)} zone(s)")

        # 6. Test zone_violations (AP-02, AP-06, BR-06)
        print("\n[6/7] Testing zone_violations (AP-02, AP-06, BR-06)...")
        entered_time = datetime.now(timezone.utc)
        violation = await create_zone_violation(
            camera_id="BAI-KIEM",
            zone_id=zone["id"],
            object_label=test_label_name,
            entered_at=entered_time,
            clip_path=f"data/clips/viol_{test_run_id}.mp4",
        )
        assert violation["id"] is not None
        assert violation["status"] == "OPEN"
        assert violation["object_label"] == test_label_name
        created_records["violations"].append(violation["id"])
        print(f"  [OK] create_zone_violation() [OPEN] created ID: {violation['id']}")

        open_viols = await get_open_violations(zone_id=zone["id"])
        assert len(open_viols) >= 1
        assert any(v["id"] == violation["id"] for v in open_viols)
        print(f"  [OK] get_open_violations(zone_id='{zone['id']}') found {len(open_viols)} open violation(s)")

        await asyncio.sleep(0.1)  # small delay for duration calculation

        closed_viol = await close_zone_violation(
            violation_id=violation["id"],
            clip_path=f"data/clips/viol_closed_{test_run_id}.mp4",
        )
        assert closed_viol is not None
        assert closed_viol["status"] == "CLOSED"
        assert closed_viol["exited_at"] is not None
        assert closed_viol["duration_seconds"] is not None
        assert closed_viol["duration_seconds"] >= 0
        print(f"  [OK] close_zone_violation() [CLOSED] duration: {closed_viol['duration_seconds']}s")

        open_viols_after = await get_open_violations(zone_id=zone["id"])
        assert not any(v["id"] == violation["id"] for v in open_viols_after)
        print(f"  [OK] get_open_violations() confirmed violation is no longer OPEN")

        recent_violations = await get_recent_zone_violations(limit=5)
        assert any(v["id"] == violation["id"] for v in recent_violations)
        print(f"  [OK] get_recent_zone_violations() includes closed violation")

    finally:
        # 7. Teardown & Clean up test records
        print("\n[7/7] Cleaning up test records & closing pool...")
        async with get_db_connection() as conn:
            # Delete in reverse foreign key order
            for vid in created_records["violations"]:
                await conn.execute("DELETE FROM zone_violations WHERE id = $1", uuid.UUID(vid))
            for zid in created_records["zones"]:
                await conn.execute("DELETE FROM zones WHERE id = $1", uuid.UUID(zid))
            for lid in created_records["labels"]:
                await conn.execute("DELETE FROM object_labels WHERE id = $1", uuid.UUID(lid))
            for eid in created_records["events"]:
                await conn.execute("DELETE FROM gate_events WHERE id = $1", uuid.UUID(eid))
            for veid in created_records["vehicles"]:
                await conn.execute("DELETE FROM registered_vehicles WHERE id = $1", uuid.UUID(veid))
        print("  [OK] Test records cleaned up successfully")

        await close_db_pool()
        print("  [OK] Database pool closed gracefully")

    print("\n" + "=" * 70)
    print("ALL TESTS PASSED SUCCESSFULLY! (100% PASS)")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_tests())

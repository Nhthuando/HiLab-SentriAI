"""
db.repositories — Database CRUD and Query Helpers for Python Worker

Implements query access patterns (AP-01 to AP-07) and lifecycle updates
for registered_vehicles, gate_events, zones, zone_violations, and object_labels.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

import asyncpg
from db.connection import get_db_pool

# Type alias for database connection or pool
DbExecutor = Union[asyncpg.Connection, asyncpg.Pool]


def _get_executor(conn_or_pool: Optional[DbExecutor] = None) -> DbExecutor:
    """Return the given executor, or fallback to the global pool."""
    if conn_or_pool is not None:
        return conn_or_pool
    return get_db_pool()


def _record_to_dict(record: Optional[asyncpg.Record]) -> Optional[Dict[str, Any]]:
    """Convert an asyncpg Record to a Python dictionary, casting UUIDs to str."""
    if record is None:
        return None
    d = dict(record)
    for k, v in d.items():
        if isinstance(v, uuid.UUID):
            d[k] = str(v)
    return d


def _records_to_list(records: List[asyncpg.Record]) -> List[Dict[str, Any]]:
    """Convert a list of asyncpg Records to Python dictionaries."""
    return [_record_to_dict(r) for r in records]  # type: ignore


# ─────────────────────────────────────────────────────────────────────────────
# Registered Vehicles (AP-01, M1, M3)
# ─────────────────────────────────────────────────────────────────────────────

async def get_vehicle_status_by_plate(
    plate_number: str,
    conn_or_pool: Optional[DbExecutor] = None,
) -> Optional[str]:
    """
    AP-01: Lookup registered vehicle status ('KNOWN' or 'STRANGER') by plate number.
    Returns None if plate is not registered.
    """
    executor = _get_executor(conn_or_pool)
    query = """
        SELECT status FROM registered_vehicles
        WHERE plate_number = $1
        LIMIT 1
    """
    row = await executor.fetchrow(query, plate_number.strip().upper())
    return row["status"] if row else None


async def get_all_registered_plates(
    conn_or_pool: Optional[DbExecutor] = None,
) -> Dict[str, str]:
    """
    Fetch all registered license plates as a mapping of plate_number -> status.
    Useful for in-memory caching during real-time LPR.
    """
    executor = _get_executor(conn_or_pool)
    query = "SELECT plate_number, status FROM registered_vehicles"
    rows = await executor.fetch(query)
    return {r["plate_number"]: r["status"] for r in rows}


async def register_vehicle(
    plate_number: str,
    status: str = "KNOWN",
    note: Optional[str] = None,
    conn_or_pool: Optional[DbExecutor] = None,
) -> Dict[str, Any]:
    """
    Insert a registered vehicle record.
    """
    executor = _get_executor(conn_or_pool)
    now = datetime.now(timezone.utc)
    rec_id = uuid.uuid4()
    query = """
        INSERT INTO registered_vehicles (id, plate_number, status, note, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING *
    """
    row = await executor.fetchrow(
        query, rec_id, plate_number.strip().upper(), status, note, now, now
    )
    return _record_to_dict(row)  # type: ignore


# ─────────────────────────────────────────────────────────────────────────────
# Gate Events (AP-02, AP-03, AP-04, M1)
# ─────────────────────────────────────────────────────────────────────────────

async def create_gate_event(
    camera_id: str,
    lane: str,
    license_plate: str,
    status: str,
    confidence: float,
    crop_path: Optional[str] = None,
    clip_path: Optional[str] = None,
    event_timestamp: Optional[datetime] = None,
    conn_or_pool: Optional[DbExecutor] = None,
) -> Dict[str, Any]:
    """
    Create a new gate event log record (append-only log).
    """
    executor = _get_executor(conn_or_pool)
    now = datetime.now(timezone.utc)
    ts = event_timestamp or now
    rec_id = uuid.uuid4()
    query = """
        INSERT INTO gate_events (
            id, camera_id, lane, license_plate, status,
            confidence, crop_path, clip_path, timestamp, created_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING *
    """
    row = await executor.fetchrow(
        query,
        rec_id,
        camera_id,
        lane,
        license_plate.strip().upper(),
        status,
        float(confidence),
        crop_path,
        clip_path,
        ts,
        now,
    )
    return _record_to_dict(row)  # type: ignore


async def get_recent_gate_events(
    limit: int = 20,
    camera_id: Optional[str] = None,
    conn_or_pool: Optional[DbExecutor] = None,
) -> List[Dict[str, Any]]:
    """
    AP-02: Query latest gate events for alert panel & live feed.
    """
    executor = _get_executor(conn_or_pool)
    if camera_id:
        query = """
            SELECT * FROM gate_events
            WHERE camera_id = $1
            ORDER BY timestamp DESC
            LIMIT $2
        """
        rows = await executor.fetch(query, camera_id, limit)
    else:
        query = """
            SELECT * FROM gate_events
            ORDER BY timestamp DESC
            LIMIT $1
        """
        rows = await executor.fetch(query, limit)
    return _records_to_list(rows)


async def get_gate_events_by_plate(
    plate_number: str,
    limit: int = 50,
    conn_or_pool: Optional[DbExecutor] = None,
) -> List[Dict[str, Any]]:
    """
    AP-03: Search gate event history for a specific license plate.
    """
    executor = _get_executor(conn_or_pool)
    query = """
        SELECT * FROM gate_events
        WHERE license_plate = $1
        ORDER BY timestamp DESC
        LIMIT $2
    """
    rows = await executor.fetch(query, plate_number.strip().upper(), limit)
    return _records_to_list(rows)


async def count_stranger_vehicles(
    start_time: datetime,
    end_time: datetime,
    conn_or_pool: Optional[DbExecutor] = None,
) -> int:
    """
    AP-04: Count stranger vehicles in a given time window (for AI Q&A).
    """
    executor = _get_executor(conn_or_pool)
    query = """
        SELECT COUNT(*) FROM gate_events
        WHERE status = 'STRANGER'
          AND timestamp >= $1
          AND timestamp < $2
    """
    count = await executor.fetchval(query, start_time, end_time)
    return count or 0


# ─────────────────────────────────────────────────────────────────────────────
# Zones (AP-05, M2, M3)
# ─────────────────────────────────────────────────────────────────────────────

async def get_active_zones_by_camera(
    camera_id: str,
    conn_or_pool: Optional[DbExecutor] = None,
) -> List[Dict[str, Any]]:
    """
    AP-05: Load active polygon zones and rules for a specific camera.
    """
    executor = _get_executor(conn_or_pool)
    query = """
        SELECT id, camera_id, name, polygon_points, rule_type, target_labels, is_active, created_at, updated_at
        FROM zones
        WHERE camera_id = $1 AND is_active = true
    """
    rows = await executor.fetch(query, camera_id)
    return _records_to_list(rows)


async def get_all_active_zones(
    conn_or_pool: Optional[DbExecutor] = None,
) -> List[Dict[str, Any]]:
    """
    Load all active zones across all cameras.
    """
    executor = _get_executor(conn_or_pool)
    query = """
        SELECT id, camera_id, name, polygon_points, rule_type, target_labels, is_active, created_at, updated_at
        FROM zones
        WHERE is_active = true
    """
    rows = await executor.fetch(query)
    return _records_to_list(rows)


async def create_zone(
    camera_id: str,
    name: str,
    polygon_points: list,
    rule_type: str = "PROHIBIT_SPECIFIED",
    target_labels: Optional[list] = None,
    is_active: bool = True,
    conn_or_pool: Optional[DbExecutor] = None,
) -> Dict[str, Any]:
    """
    Create a new monitoring zone.
    """
    executor = _get_executor(conn_or_pool)
    now = datetime.now(timezone.utc)
    rec_id = uuid.uuid4()
    labels = target_labels if target_labels is not None else []
    query = """
        INSERT INTO zones (
            id, camera_id, name, polygon_points, rule_type, target_labels, is_active, created_at, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING *
    """
    row = await executor.fetchrow(
        query, rec_id, camera_id, name, polygon_points, rule_type, labels, is_active, now, now
    )
    return _record_to_dict(row)  # type: ignore


# ─────────────────────────────────────────────────────────────────────────────
# Zone Violations (AP-02, AP-06, BR-06, M2)
# ─────────────────────────────────────────────────────────────────────────────

async def create_zone_violation(
    camera_id: str,
    zone_id: Union[str, uuid.UUID],
    object_label: str,
    entered_at: Optional[datetime] = None,
    clip_path: Optional[str] = None,
    violation_id: Optional[Union[str, uuid.UUID]] = None,
    conn_or_pool: Optional[DbExecutor] = None,
) -> Dict[str, Any]:
    """
    Create an OPEN zone violation when an unauthorized object enters a zone.
    """
    executor = _get_executor(conn_or_pool)
    now = datetime.now(timezone.utc)
    ts = entered_at or now
    rec_id = (
        uuid.UUID(violation_id)
        if isinstance(violation_id, str)
        else violation_id or uuid.uuid4()
    )
    zid = uuid.UUID(zone_id) if isinstance(zone_id, str) else zone_id
    query = """
        INSERT INTO zone_violations (
            id, camera_id, zone_id, object_label, status,
            entered_at, clip_path, created_at
        )
        VALUES ($1, $2, $3, $4, 'OPEN', $5, $6, $7)
        RETURNING *
    """
    row = await executor.fetchrow(
        query, rec_id, camera_id, zid, object_label, ts, clip_path, now
    )
    return _record_to_dict(row)  # type: ignore


async def close_zone_violation(
    violation_id: Union[str, uuid.UUID],
    exited_at: Optional[datetime] = None,
    duration_seconds: Optional[int] = None,
    clip_path: Optional[str] = None,
    conn_or_pool: Optional[DbExecutor] = None,
) -> Optional[Dict[str, Any]]:
    """
    Close an active zone violation when the object exits the zone.
    Calculates duration_seconds if not explicitly provided.
    """
    executor = _get_executor(conn_or_pool)
    now = datetime.now(timezone.utc)
    exit_ts = exited_at or now
    vid = uuid.UUID(violation_id) if isinstance(violation_id, str) else violation_id

    # If duration_seconds not provided, fetch entered_at and calculate
    dur = duration_seconds
    if dur is None:
        row = await executor.fetchrow(
            "SELECT entered_at FROM zone_violations WHERE id = $1", vid
        )
        if row and row["entered_at"]:
            dur = max(0, int((exit_ts - row["entered_at"]).total_seconds()))

    query = """
        UPDATE zone_violations
        SET status = 'CLOSED',
            exited_at = $2,
            duration_seconds = $3,
            clip_path = COALESCE($4, clip_path)
        WHERE id = $1
        RETURNING *
    """
    updated_row = await executor.fetchrow(query, vid, exit_ts, dur, clip_path)
    return _record_to_dict(updated_row)


async def get_open_violations(
    zone_id: Optional[Union[str, uuid.UUID]] = None,
    camera_id: Optional[str] = None,
    conn_or_pool: Optional[DbExecutor] = None,
) -> List[Dict[str, Any]]:
    """
    Query currently OPEN violations (used by worker to track active objects and avoid spamming alerts).
    """
    executor = _get_executor(conn_or_pool)
    if zone_id and camera_id:
        zid = uuid.UUID(zone_id) if isinstance(zone_id, str) else zone_id
        query = "SELECT * FROM zone_violations WHERE zone_id = $1 AND camera_id = $2 AND status = 'OPEN'"
        rows = await executor.fetch(query, zid, camera_id)
    elif zone_id:
        zid = uuid.UUID(zone_id) if isinstance(zone_id, str) else zone_id
        query = "SELECT * FROM zone_violations WHERE zone_id = $1 AND status = 'OPEN'"
        rows = await executor.fetch(query, zid)
    elif camera_id:
        query = "SELECT * FROM zone_violations WHERE camera_id = $1 AND status = 'OPEN'"
        rows = await executor.fetch(query, camera_id)
    else:
        query = "SELECT * FROM zone_violations WHERE status = 'OPEN'"
        rows = await executor.fetch(query)
    return _records_to_list(rows)


async def get_recent_zone_violations(
    limit: int = 20,
    conn_or_pool: Optional[DbExecutor] = None,
) -> List[Dict[str, Any]]:
    """
    AP-02: Query latest zone violations for alert panel.
    """
    executor = _get_executor(conn_or_pool)
    query = """
        SELECT * FROM zone_violations
        ORDER BY entered_at DESC
        LIMIT $1
    """
    rows = await executor.fetch(query, limit)
    return _records_to_list(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Object Labels (M3, AC-06)
# ─────────────────────────────────────────────────────────────────────────────

async def get_all_object_labels(
    conn_or_pool: Optional[DbExecutor] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch all object labels (Vietnamese name -> base YOLO class mapping).
    """
    executor = _get_executor(conn_or_pool)
    query = "SELECT id, vietnamese_name, base_class, created_at, updated_at FROM object_labels ORDER BY vietnamese_name ASC"
    rows = await executor.fetch(query)
    return _records_to_list(rows)


async def create_object_label(
    vietnamese_name: str,
    base_class: str,
    conn_or_pool: Optional[DbExecutor] = None,
) -> Dict[str, Any]:
    """
    Insert a new object label category.
    """
    executor = _get_executor(conn_or_pool)
    now = datetime.now(timezone.utc)
    rec_id = uuid.uuid4()
    query = """
        INSERT INTO object_labels (id, vietnamese_name, base_class, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING *
    """
    row = await executor.fetchrow(query, rec_id, vietnamese_name.strip(), base_class.strip(), now, now)
    return _record_to_dict(row)  # type: ignore


async def update_violation_clip_path(
    violation_id: Union[str, uuid.UUID],
    clip_path: str,
    conn_or_pool: Optional[DbExecutor] = None,
) -> Optional[Dict[str, Any]]:
    """
    Update clip_path on a zone violation after 10s clip generation completes.
    """
    executor = _get_executor(conn_or_pool)
    vid = uuid.UUID(violation_id) if isinstance(violation_id, str) else violation_id
    query = """
        UPDATE zone_violations
        SET clip_path = $2
        WHERE id = $1
        RETURNING *
    """
    row = await executor.fetchrow(query, vid, clip_path)
    return _record_to_dict(row)


async def close_stale_open_violations(
    camera_id: str = "BAI-KIEM",
    exit_timestamp: Optional[datetime] = None,
    conn_or_pool: Optional[DbExecutor] = None,
) -> int:
    """
    Close orphan OPEN violations on worker startup to prevent stale tracking rows.
    Preserves existing clip_path and sets status='CLOSED'.
    """
    executor = _get_executor(conn_or_pool)
    now = exit_timestamp or datetime.now(timezone.utc)
    query = """
        UPDATE zone_violations
        SET status = 'CLOSED',
            exited_at = COALESCE(exited_at, $2),
            duration_seconds = COALESCE(duration_seconds, GREATEST(0, FLOOR(EXTRACT(EPOCH FROM ($2 - entered_at)))::int))
        WHERE camera_id = $1 AND status = 'OPEN'
    """
    res = await executor.execute(query, camera_id, now)
    try:
        count = int(res.split()[-1])
        return count
    except Exception:
        return 0


async def get_active_custom_model(
    conn_or_pool: Optional[DbExecutor] = None,
) -> Optional[Dict[str, Any]]:
    """Load only the active custom augmentation; base YOLO is intentionally absent."""
    executor = _get_executor(conn_or_pool)
    row = await executor.fetchrow(
        """
        SELECT version_key, artifact_path, artifact_sha256, evaluation_metrics
        FROM model_versions
        WHERE status = 'ACTIVE'
        LIMIT 1
        """
    )
    result = _record_to_dict(row)
    if result and isinstance(result.get("evaluation_metrics"), str):
        try:
            result["evaluation_metrics"] = json.loads(result["evaluation_metrics"])
        except json.JSONDecodeError:
            result["evaluation_metrics"] = {}
    return result

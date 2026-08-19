"""
SentriAI Python Worker — Database Module (db)

Provides asyncpg connection pooling and repository functions for Neon PostgreSQL.
"""
from db.connection import (
    check_db_health,
    close_db_pool,
    get_database_url,
    get_db_connection,
    get_db_pool,
    init_db_pool,
)
from db.repositories import (
    close_stale_open_violations,
    close_zone_violation,
    count_stranger_vehicles,
    create_gate_event,
    create_object_label,
    create_zone,
    create_zone_violation,
    get_active_zones_by_camera,
    get_all_active_zones,
    get_all_object_labels,
    get_all_registered_plates,
    get_gate_events_by_plate,
    get_open_violations,
    get_recent_gate_events,
    get_recent_zone_violations,
    get_vehicle_status_by_plate,
    register_vehicle,
    update_violation_clip_path,
)

__all__ = [
    # Connection
    "init_db_pool",
    "get_db_pool",
    "close_db_pool",
    "get_db_connection",
    "check_db_health",
    "get_database_url",
    # Vehicles
    "get_vehicle_status_by_plate",
    "get_all_registered_plates",
    "register_vehicle",
    # Gate Events
    "create_gate_event",
    "get_recent_gate_events",
    "get_gate_events_by_plate",
    "count_stranger_vehicles",
    # Zones
    "get_active_zones_by_camera",
    "get_all_active_zones",
    "create_zone",
    # Zone Violations
    "create_zone_violation",
    "close_zone_violation",
    "get_open_violations",
    "get_recent_zone_violations",
    "update_violation_clip_path",
    "close_stale_open_violations",
    # Object Labels
    "get_all_object_labels",
    "create_object_label",
]

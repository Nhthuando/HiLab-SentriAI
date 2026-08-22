"""
zone.zone_sync — 5-Second Background Synchronizer for Monitoring Zones and Object Labels

Loads active polygon zones for camera BAI-KIEM and object-label mappings from DB,
maintaining an atomic snapshot for the real-time AI worker loop (BR-07, Flow 1).
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from db.repositories import get_active_zones_by_camera, get_all_object_labels

logger = logging.getLogger("sentriai.zone.sync")


@dataclass(frozen=True)
class ZoneSnapshot:
    """Immutable snapshot of active zones and object label mappings."""
    zones: List[Dict[str, Any]] = field(default_factory=list)
    class_to_labels: Dict[str, List[str]] = field(default_factory=dict)
    all_labels: List[Dict[str, Any]] = field(default_factory=list)


class ZoneSynchronizer:
    """
    Polls Neon PostgreSQL every 5 seconds to keep zones and object labels up to date.
    Keeps last known good snapshot on database connection errors.
    """

    def __init__(self, camera_id: str = "BAI-KIEM", sync_interval: float = 5.0):
        self.camera_id = camera_id
        self.sync_interval = sync_interval
        self._snapshot = ZoneSnapshot()
        self._lock = asyncio.Lock()
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def get_snapshot(self) -> ZoneSnapshot:
        """Return the current atomic snapshot synchronously."""
        return self._snapshot

    async def refresh_now(self) -> bool:
        """
        Fetch latest active zones and object labels from database immediately.
        Returns True if successful, False if failed (keeping previous snapshot).
        """
        try:
            raw_zones = await get_active_zones_by_camera(self.camera_id)
            raw_labels = await get_all_object_labels()

            # Build base_class -> sorted vietnamese_name[] mapping
            class_map: Dict[str, List[str]] = {}
            for lbl in raw_labels:
                b_cls = (lbl.get("base_class") or "").strip().casefold()
                vn_name = (lbl.get("vietnamese_name") or "").strip()
                # Compatibility repair for older projects where every heavy
                # vehicle label was saved as `truck`. Keep user data intact but
                # expose precise runtime classes to YOLO-World.
                vn_folded = vn_name.casefold()
                if vn_folded == "container":
                    b_cls = "container"
                elif vn_folded in {"xe nâng", "xe cẩu"}:
                    b_cls = "forklift"
                elif vn_folded in {"xe chở người", "xe cho người"}:
                    b_cls = "personnel_carrier"
                if b_cls and vn_name:
                    if b_cls not in class_map:
                        class_map[b_cls] = []
                    if vn_name not in class_map[b_cls]:
                        class_map[b_cls].append(vn_name)

            for b_cls in class_map:
                class_map[b_cls].sort()

            # Clean and normalize zones
            cleaned_zones: List[Dict[str, Any]] = []
            for z in raw_zones:
                cleaned_zones.append({
                    "id": str(z["id"]),
                    "name": z.get("name", "Zone"),
                    "polygon": z.get("polygon_points", []),
                    "polygon_points": z.get("polygon_points", []),
                    "ruleType": z.get("rule_type", "PROHIBIT_SPECIFIED"),
                    "rule_type": z.get("rule_type", "PROHIBIT_SPECIFIED"),
                    "targetLabels": z.get("target_labels", []),
                    "target_labels": z.get("target_labels", []),
                    "isActive": z.get("is_active", True),
                })

            new_snapshot = ZoneSnapshot(
                zones=cleaned_zones,
                class_to_labels=class_map,
                all_labels=raw_labels,
            )

            async with self._lock:
                self._snapshot = new_snapshot

            logger.debug(
                "[%s] Zone sync updated: %d active zones, %d label categories",
                self.camera_id,
                len(cleaned_zones),
                len(raw_labels),
            )
            return True
        except Exception as exc:
            logger.warning(
                "[%s] Failed to refresh zone/label snapshot from database (%s). Preserving existing snapshot.",
                self.camera_id,
                exc,
            )
            return False

    async def _sync_loop(self) -> None:
        """Background polling loop."""
        logger.info("[%s] Starting zone synchronizer loop (interval: %.1fs)...", self.camera_id, self.sync_interval)
        while self._running:
            await self.refresh_now()
            try:
                await asyncio.sleep(self.sync_interval)
            except asyncio.CancelledError:
                break
        logger.info("[%s] Zone synchronizer loop stopped.", self.camera_id)

    def start(self) -> None:
        """Start background polling task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._sync_loop())

    async def stop(self) -> None:
        """Stop background polling task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            self._task = None

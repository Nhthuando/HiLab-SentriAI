import asyncio

from db.repositories import create_gate_event


def test_gate_event_ensures_vehicle_exists_without_overwriting_user_label():
    class FakeExecutor:
        def __init__(self):
            self.execute_call = None
            self.event_call = None
            self.calls = []

        async def execute(self, query, *args):
            self.calls.append("vehicle")
            self.execute_call = (query, args)
            return "INSERT 0 1"

        async def fetchrow(self, query, *args):
            self.calls.append("event")
            self.event_call = (query, args)
            return {"id": args[0], "license_plate": args[5], "status": args[6]}

    async def exercise():
        executor = FakeExecutor()
        await create_gate_event(
            camera_id="GATE-01",
            lane="IN_1",
            license_plate="15rm-032.98",
            status="STRANGER",
            confidence=0.99,
            conn_or_pool=executor,
        )

        vehicle_query, vehicle_args = executor.execute_call
        assert "ON CONFLICT (plate_number) DO NOTHING" in vehicle_query
        assert vehicle_args[1] == "15RM-032.98"
        assert vehicle_args[2] == "STRANGER"
        assert executor.event_call[1][5] == "15RM-032.98"
        assert executor.calls == ["event", "vehicle"]

    asyncio.run(exercise())


def test_failed_journal_insert_never_creates_vehicle_setting_row():
    class FailingExecutor:
        def __init__(self):
            self.vehicle_inserted = False

        async def fetchrow(self, _query, *_args):
            raise RuntimeError("event insert failed")

        async def execute(self, _query, *_args):
            self.vehicle_inserted = True

    async def exercise():
        executor = FailingExecutor()
        try:
            await create_gate_event(
                camera_id="GATE-01",
                lane="IN_1",
                license_plate="15R-105.17",
                status="STRANGER",
                confidence=0.99,
                conn_or_pool=executor,
            )
        except RuntimeError:
            pass
        assert executor.vehicle_inserted is False

    asyncio.run(exercise())


def test_unknown_journal_event_is_not_added_to_vehicle_settings():
    class FakeExecutor:
        def __init__(self):
            self.vehicle_inserted = False

        async def fetchrow(self, _query, *args):
            return {"id": args[0], "license_plate": args[5], "status": args[6]}

        async def execute(self, _query, *_args):
            self.vehicle_inserted = True

    async def exercise():
        executor = FakeExecutor()
        event = await create_gate_event(
            camera_id="GATE-01",
            lane="IN_1",
            license_plate="UNKNOWN",
            status="STRANGER",
            confidence=0.0,
            conn_or_pool=executor,
        )

        assert event["license_plate"] == "UNKNOWN"
        assert executor.vehicle_inserted is False

    asyncio.run(exercise())

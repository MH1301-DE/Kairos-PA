from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.connectors.types import CanonicalRecord
from kairos.db.models import CalendarEvent


class CalendarEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_from_records(
        self, user_id: UUID, connector: str, records: list[CanonicalRecord]
    ) -> int:
        written = 0
        for record in records:
            if not record.external_id:
                continue
            data = record.data
            if not isinstance(data, dict):
                continue
            stmt = (
                insert(CalendarEvent)
                .values(
                    user_id=user_id,
                    connector=connector,
                    external_id=record.external_id,
                    summary=data.get("summary"),
                    description=data.get("description"),
                    location=data.get("location"),
                    start_at=datetime.fromisoformat(str(data["start_at"])),
                    end_at=datetime.fromisoformat(str(data["end_at"])),
                    all_day=bool(data.get("all_day", False)),
                    status=str(data.get("status", "confirmed")),
                    source="external",
                )
                .on_conflict_do_update(
                    constraint="uq_calendar_event",
                    set_={
                        "summary": data.get("summary"),
                        "description": data.get("description"),
                        "location": data.get("location"),
                        "start_at": datetime.fromisoformat(str(data["start_at"])),
                        "end_at": datetime.fromisoformat(str(data["end_at"])),
                        "all_day": bool(data.get("all_day", False)),
                        "status": str(data.get("status", "confirmed")),
                        "updated_at": datetime.now(UTC),
                    },
                )
            )
            await self._session.execute(stmt)
            written += 1
        return written

    async def upsert_kairos_event(
        self,
        user_id: UUID,
        connector: str,
        external_id: str,
        summary: str,
        start_at: datetime,
        end_at: datetime,
        description: str | None,
    ) -> None:
        stmt = (
            insert(CalendarEvent)
            .values(
                user_id=user_id,
                connector=connector,
                external_id=external_id,
                summary=summary,
                description=description,
                start_at=start_at,
                end_at=end_at,
                all_day=False,
                status="confirmed",
                source="kairos",
            )
            .on_conflict_do_update(
                constraint="uq_calendar_event",
                set_={"summary": summary, "description": description},
            )
        )
        await self._session.execute(stmt)

    async def list_between(
        self, user_id: UUID, start: datetime, end: datetime
    ) -> list[CalendarEvent]:
        result = await self._session.execute(
            select(CalendarEvent)
            .where(
                CalendarEvent.user_id == user_id,
                CalendarEvent.status != "cancelled",
                CalendarEvent.start_at < end,
                CalendarEvent.end_at > start,
            )
            .order_by(CalendarEvent.start_at)
        )
        return list(result.scalars().all())

    async def mark_deleted(self, user_id: UUID, connector: str, external_id: str) -> None:
        await self._session.execute(
            update(CalendarEvent)
            .where(
                CalendarEvent.user_id == user_id,
                CalendarEvent.connector == connector,
                CalendarEvent.external_id == external_id,
            )
            .values(status="cancelled")
        )

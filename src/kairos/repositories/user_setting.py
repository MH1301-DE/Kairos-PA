from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.models import UserSetting


@dataclass(frozen=True)
class UserSettingData:
    birth_date: date | None
    sex: str | None
    resting_hr_override: int | None
    hr_max_override: int | None
    sleep_target_hours: float
    llm_model: str


_DEFAULT = UserSettingData(
    birth_date=None,
    sex=None,
    resting_hr_override=None,
    hr_max_override=None,
    sleep_target_hours=8.0,
    llm_model="anthropic/claude-sonnet-5",
)


async def get_or_default_user_setting(session: AsyncSession, *, user_id: UUID) -> UserSettingData:
    row = (
        await session.execute(select(UserSetting).where(UserSetting.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        return _DEFAULT
    return UserSettingData(
        birth_date=row.birth_date,
        sex=row.sex,
        resting_hr_override=row.resting_hr_override,
        hr_max_override=row.hr_max_override,
        sleep_target_hours=row.sleep_target_hours,
        llm_model=row.llm_model,
    )


async def upsert_profile(
    session: AsyncSession,
    *,
    user_id: UUID,
    birth_date: date | None,
    hr_max_override: int | None,
    resting_hr_override: int | None,
) -> None:
    values = {
        "birth_date": birth_date,
        "hr_max_override": hr_max_override,
        "resting_hr_override": resting_hr_override,
    }
    stmt = pg_insert(UserSetting).values(user_id=user_id, **values)
    await session.execute(stmt.on_conflict_do_update(index_elements=["user_id"], set_=values))


async def measured_max_hr_12m(session: AsyncSession, *, user_id: UUID) -> int | None:
    result = await session.execute(
        text(
            "SELECT max(max_hr) FROM activity "
            "WHERE user_id = :u AND deleted_at IS NULL "
            "AND start_at >= now() - interval '12 months'"
        ),
        {"u": user_id},
    )
    value = result.scalar_one_or_none()
    return int(value) if value is not None else None

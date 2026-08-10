from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.models import UserSetting


@dataclass(frozen=True)
class UserSettingData:
    birth_date: date | None
    sex: str | None
    resting_hr_override: int | None
    hr_max_override: int | None
    sleep_target_hours: float


_DEFAULT = UserSettingData(
    birth_date=None,
    sex=None,
    resting_hr_override=None,
    hr_max_override=None,
    sleep_target_hours=8.0,
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
    )

from __future__ import annotations

from datetime import date

from kairos.metrics.hr_zones import resolve_hr_max
from kairos.repositories.user_setting import UserSettingData

HR_MAX_MISSING_NOTE = "HFmax fehlt – bitte in den Einstellungen eintragen"


def hr_max_for(setting: UserSettingData, as_of: date) -> int | None:
    return resolve_hr_max(setting.birth_date, setting.hr_max_override, as_of=as_of)[0]

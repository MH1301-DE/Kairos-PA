from __future__ import annotations

from kairos.metrics.registry import MetricRegistry
from kairos.metrics.variants.acwr_variant import AcwrVariant
from kairos.metrics.variants.banister_trimp_variant import BanisterTrimpVariant
from kairos.metrics.variants.edwards_trimp_variant import EdwardsTrimpVariant
from kairos.metrics.variants.hr_zone_distribution_variant import (
    HrZoneDistributionKarvonenVariant,
    HrZoneDistributionPercentMaxVariant,
)
from kairos.metrics.variants.hrv_baseline_variant import HrvBaselineVariant
from kairos.metrics.variants.monotony_strain_variant import MonotonyStrainVariant
from kairos.metrics.variants.resting_hr_trend_variant import RestingHrTrendVariant
from kairos.metrics.variants.sleep_debt_variant import SleepDebtVariant
from kairos.metrics.variants.training_load_variant import TrainingLoadVariant


def build_default_registry() -> MetricRegistry:
    registry = MetricRegistry()
    registry.register(EdwardsTrimpVariant())
    registry.register(BanisterTrimpVariant())
    registry.register(HrZoneDistributionPercentMaxVariant())
    registry.register(HrZoneDistributionKarvonenVariant())
    registry.register(TrainingLoadVariant())
    registry.register(AcwrVariant())
    registry.register(MonotonyStrainVariant())
    registry.register(HrvBaselineVariant())
    registry.register(SleepDebtVariant())
    registry.register(RestingHrTrendVariant())
    return registry

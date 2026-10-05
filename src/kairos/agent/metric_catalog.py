from __future__ import annotations

from dataclasses import dataclass

from kairos.metrics.bootstrap import build_default_registry


@dataclass(frozen=True)
class MetricInfo:
    description: str
    value_shape: str
    # only scalar metrics get a metric_daily_value series (see recompute_metric_daily_values)
    daily_series: bool


METRIC_CATALOG: dict[str, MetricInfo] = {
    "trimp": MetricInfo(
        "Trainingsbelastung eines einzelnen Tages aus Herzfrequenz und Dauer.",
        "Zahl in TRIMP-Punkten (0 = kein Training)", True,
    ),
    "training_load": MetricInfo(
        "Fitness (CTL, 42 Tage), Ermüdung (ATL, 7 Tage) und Form (TSB = CTL - ATL).",
        "Objekt {ctl, atl, tsb}", False,
    ),
    "acwr": MetricInfo(
        "Verhältnis akute (7 Tage) zu chronischer (28 Tage) Belastung; > 1,5 = Verletzungsrisiko.",
        "Objekt {ratio}", False,
    ),
    "monotony_strain": MetricInfo(
        "Foster-Monotonie und -Strain der letzten 7 Tage (Gleichförmigkeit der Belastung).",
        "Objekt {monotony, strain}", False,
    ),
    "hr_zone_distribution": MetricInfo(
        "Sekunden in den Herzfrequenzzonen am gewählten Tag.",
        "Objekt {Zonenname: Sekunden}", False,
    ),
    "hrv_baseline": MetricInfo(
        "Heutige HRV gegen das persönliche Baseline-Band der letzten 60 Tage.",
        "Objekt {today, baseline_mean, baseline_low, baseline_high} in ms", False,
    ),
    "resting_hr_trend": MetricInfo(
        "Ruhepuls der letzten Tage gegen den Zeitraum davor.",
        "Objekt {recent_avg, prior_avg, delta_bpm} in bpm", False,
    ),
    "sleep_debt": MetricInfo(
        "Schlafdefizit der letzten 7 Nächte gegen das persönliche Schlafziel.",
        "Zahl in Stunden", True,
    ),
}


def render_metric_catalog() -> str:
    registry = build_default_registry()
    lines = ["VERFÜGBARE KENNZAHLEN (metric_id für query_health/analyze_records):"]
    for metric_id in registry.metric_ids():
        info = METRIC_CATALOG[metric_id]
        variants = ", ".join(registry.variants_for(metric_id))
        series = "ja" if info.daily_series else "nein"
        lines.append(
            f"- {metric_id} (Varianten: {variants}): {info.description} "
            f"Wert: {info.value_shape}. Zeitreihe: {series}."
        )
    lines.append(
        "analyze_records funktioniert nur für Kennzahlen mit Zeitreihe: ja. "
        "Für alle anderen query_health mit as_of für einzelne Tage nutzen."
    )
    return "\n".join(lines)

"""activity_fields_and_metric_def_seeds

Revision ID: c4d2e3f5a6b7
Revises: b3c1e2f4a5d6
Create Date: 2026-08-05 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d2e3f5a6b7"
down_revision: Union[str, None] = "b3c1e2f4a5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_METRICS = [
    ("hr",           "Heart Rate",                "bpm"),
    ("stress",       "Stress Level",              "0–100"),
    ("body_battery", "Body Battery",              "0–100"),
    ("hrv_5min",     "HRV 5-min Average",         "ms"),
    ("respiration",  "Respiration Rate",          "breaths/min"),
    ("spo2",         "Blood Oxygen Saturation",   "%"),
    ("cadence",      "Cadence",                   "rpm"),
    ("speed_mps",    "Speed",                     "m/s"),
    ("power_w",      "Power",                     "W"),
    ("altitude_m",   "Altitude",                  "m"),
    ("lat_deg",      "GPS Latitude",              "°"),
    ("lng_deg",      "GPS Longitude",             "°"),
    ("temp_c",       "Temperature",               "°C"),
]


def upgrade() -> None:
    op.add_column("activity", sa.Column("name", sa.Text(), nullable=True))
    op.add_column("activity", sa.Column("sport", sa.Text(), nullable=True))
    op.add_column("activity", sa.Column("distance_m", sa.Float(), nullable=True))
    op.add_column("activity", sa.Column("duration_s", sa.Float(), nullable=True))
    op.add_column("activity", sa.Column("avg_hr", sa.SmallInteger(), nullable=True))
    op.add_column("activity", sa.Column("max_hr", sa.SmallInteger(), nullable=True))
    op.add_column("activity", sa.Column("elevation_gain_m", sa.Float(), nullable=True))
    op.add_column("activity", sa.Column("calories", sa.Integer(), nullable=True))
    op.add_column("activity", sa.Column("fit_object_key", sa.Text(), nullable=True))

    metric_def = sa.table(
        "metric_def",
        sa.column("code", sa.Text),
        sa.column("display_name", sa.Text),
        sa.column("unit", sa.Text),
    )
    op.bulk_insert(metric_def, [
        {"code": code, "display_name": name, "unit": unit}
        for code, name, unit in _METRICS
    ])


def downgrade() -> None:
    op.execute("DELETE FROM metric_def WHERE code IN (%s)" % ",".join(
        f"'{c}'" for c, _, _ in _METRICS
    ))
    for col in ("fit_object_key", "calories", "elevation_gain_m", "max_hr",
                "avg_hr", "duration_s", "distance_m", "sport", "name"):
        op.drop_column("activity", col)

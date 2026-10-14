import uuid
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, DOUBLE_PRECISION, JSONB, REAL, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    google_sub: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    home_timezone: Mapped[str] = mapped_column(Text, nullable=False, default="Europe/Berlin")
    role: Mapped[str] = mapped_column(Text, nullable=False, default="user")
    dek_wrapped: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')", name="app_user_role_check"),
    )


class UserSetting(Base):
    __tablename__ = "user_setting"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    birth_date: Mapped[date | None] = mapped_column(Date)
    sex: Mapped[str | None] = mapped_column(Text)
    resting_hr_override: Mapped[int | None] = mapped_column(SmallInteger)
    hr_max_override: Mapped[int | None] = mapped_column(SmallInteger)
    sleep_target_hours: Mapped[float] = mapped_column(Float, nullable=False, default=8.0)
    work_hours_start: Mapped[time | None] = mapped_column(Time)
    work_hours_end: Mapped[time | None] = mapped_column(Time)
    calendar_buffer_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=15)
    min_free_block_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=30)
    llm_model: Mapped[str] = mapped_column(
        Text, nullable=False, default="anthropic/claude-sonnet-5"
    )

    __table_args__ = (
        CheckConstraint("sex IN ('male', 'female')", name="user_setting_sex_check"),
    )


class Connection(Base):
    __tablename__ = "connection"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    connector: Mapped[str] = mapped_column(Text, nullable=False)
    external_account: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    credentials_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    # set after every successful token refresh; used to detect stale refresh tokens proactively
    token_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # set when status first becomes reauth_required; cleared on successful re-login
    reauth_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('active','reauth_required','disabled','error')",
            name="connection_status_check",
        ),
        UniqueConstraint("user_id", "connector", "external_account", name="uq_connection"),
    )


class CalendarEvent(Base):
    __tablename__ = "calendar_event"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    connector: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    calendar_id: Mapped[str] = mapped_column(Text, nullable=False, default="primary")
    summary: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="confirmed")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="external")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "connector", "external_id", name="uq_calendar_event"),
        CheckConstraint(
            "status IN ('confirmed', 'tentative', 'cancelled')",
            name="calendar_event_status_check",
        ),
        CheckConstraint("source IN ('external', 'kairos')", name="calendar_event_source_check"),
    )


class RawPayload(Base):
    __tablename__ = "raw_payload"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    connector: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    payload_gzip: Mapped[bytes | None] = mapped_column(LargeBinary)
    object_key: Mapped[str | None] = mapped_column(Text)
    payload_format: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="json_gzip"
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "connector", "kind", "window_start", "content_hash",
            name="uq_raw_payload",
        ),
        CheckConstraint(
            "payload_format IN ('json_gzip', 'fit_zip')",
            name="raw_payload_payload_format_check",
        ),
    )


class SyncState(Base):
    __tablename__ = "sync_state"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    )
    connector: Mapped[str] = mapped_column(Text, nullable=False, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False, primary_key=True)
    synced_through: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backfill_cursor: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backfill_complete_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backfill_complete_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_token: Mapped[str | None] = mapped_column(Text)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class SyncFailure(Base):
    __tablename__ = "sync_failure"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    connector: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    details: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MetricDef(Base):
    __tablename__ = "metric_def"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataSource(Base):
    __tablename__ = "data_source"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    connector: Mapped[str] = mapped_column(Text, nullable=False)
    external_account: Mapped[str | None] = mapped_column(Text)
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "connector", "source_key", name="uq_data_source"),
    )


class WellnessSample(Base):
    __tablename__ = "wellness_sample"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    metric_id: Mapped[int] = mapped_column(
        ForeignKey("metric_def.id", ondelete="RESTRICT"),
        nullable=False,
    )
    data_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_source.id", ondelete="SET NULL")
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    quality: Mapped[str] = mapped_column(String(16), nullable=False, server_default="ok")
    raw_payload_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_payload.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "metric_id", "observed_at", name="uq_wellness_sample"),
    )


class SleepSession(Base):
    __tablename__ = "sleep_session"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    data_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_source.id", ondelete="SET NULL")
    )
    raw_payload_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_payload.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "external_id", name="uq_sleep_session"),
    )


class Activity(Base):
    __tablename__ = "activity"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    sport: Mapped[str | None] = mapped_column(Text)
    sport_profile: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'generic'")
    )
    garmin_type_id: Mapped[int | None] = mapped_column(Integer)
    garmin_parent_type_id: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    start_local: Mapped[datetime | None] = mapped_column(DateTime)
    utc_offset_min: Mapped[int | None] = mapped_column(SmallInteger)
    moving_duration_s: Mapped[float | None] = mapped_column(REAL)
    avg_speed_mps: Mapped[float | None] = mapped_column(REAL)
    lap_count: Mapped[int | None] = mapped_column(SmallInteger)
    garmin_training_load: Mapped[float | None] = mapped_column(REAL)
    garmin_vo2max: Mapped[float | None] = mapped_column(REAL)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_reason: Mapped[str | None] = mapped_column(Text)
    distance_m: Mapped[float | None] = mapped_column(Float)
    duration_s: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[int | None] = mapped_column(SmallInteger)
    max_hr: Mapped[int | None] = mapped_column(SmallInteger)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)
    calories: Mapped[int | None] = mapped_column(Integer)
    fit_payload_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("raw_payload.id", ondelete="SET NULL")
    )
    data_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_source.id", ondelete="SET NULL")
    )
    raw_payload_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_payload.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "external_id", name="uq_activity"),
        CheckConstraint(
            "sport_profile IN ('running', 'cycling', 'swimming', 'hiking', 'generic')",
            name="activity_sport_profile_check",
        ),
        CheckConstraint(
            "deleted_reason IS NULL OR deleted_reason IN ('kairos', 'garmin_sync')",
            name="activity_deleted_reason_check",
        ),
        Index(
            "ix_activity_user_start_live",
            "user_id",
            text("start_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_activity_user_profile_start", "user_id", "sport_profile", text("start_at DESC")),
    )


class ActivityStreamAxis(Base):
    __tablename__ = "activity_stream_axis"

    activity_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("activity.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    t_offset_s: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    algo_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "source IN ('fit_zip', 'fit_json')", name="activity_stream_axis_source_check"
        ),
    )


class ActivityStream(Base):
    __tablename__ = "activity_stream"

    activity_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("activity.id", ondelete="CASCADE"), primary_key=True
    )
    channel: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    v4: Mapped[list[float | None] | None] = mapped_column(ARRAY(REAL))
    v8: Mapped[list[float | None] | None] = mapped_column(ARRAY(DOUBLE_PRECISION))

    __table_args__ = (
        CheckConstraint("num_nonnulls(v4, v8) = 1", name="activity_stream_one_array_check"),
    )


def _uid() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )


def _act_pk() -> Mapped[int]:
    return mapped_column(
        BigInteger, ForeignKey("activity.id", ondelete="CASCADE"), primary_key=True
    )


def _real() -> Mapped[float | None]:
    return mapped_column(REAL)


def _small() -> Mapped[int | None]:
    return mapped_column(SmallInteger)


class ActivityStats(Base):
    __tablename__ = "activity_stats"

    activity_id: Mapped[int] = _act_pk()
    user_id: Mapped[uuid.UUID] = _uid()
    sport_profile: Mapped[str] = mapped_column(Text, nullable=False)
    algo_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    distance_m: Mapped[float | None] = _real()
    elapsed_s: Mapped[float | None] = _real()
    timer_s: Mapped[float | None] = _real()
    moving_s: Mapped[float | None] = _real()
    avg_pace_s_km: Mapped[float | None] = _real()
    avg_moving_pace_s_km: Mapped[float | None] = _real()
    avg_speed_kmh: Mapped[float | None] = _real()
    max_speed_kmh: Mapped[float | None] = _real()
    avg_pace_s_100m: Mapped[float | None] = _real()
    hr_avg: Mapped[int | None] = _small()
    hr_median: Mapped[int | None] = _small()
    hr_min: Mapped[int | None] = _small()
    hr_max: Mapped[int | None] = _small()
    hr_zone_s: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    trimp_edwards: Mapped[float | None] = _real()
    elev_gain_m: Mapped[float | None] = _real()
    elev_loss_m: Mapped[float | None] = _real()
    alt_min_m: Mapped[float | None] = _real()
    alt_max_m: Mapped[float | None] = _real()
    cadence_avg: Mapped[float | None] = _real()
    power_avg_w: Mapped[float | None] = _real()
    power_max_w: Mapped[float | None] = _real()
    fastest_split_idx: Mapped[int | None] = _small()
    fastest_split_pace_s: Mapped[float | None] = _real()
    slowest_split_idx: Mapped[int | None] = _small()
    slowest_split_pace_s: Mapped[float | None] = _real()
    pace_cv_pct: Mapped[float | None] = _real()
    decoupling_pct: Mapped[float | None] = _real()
    decoupling_note: Mapped[str | None] = mapped_column(Text)
    distance_source: Mapped[str | None] = mapped_column(Text)
    hr_coverage_pct: Mapped[float | None] = _real()
    gps_coverage_pct: Mapped[float | None] = _real()
    quality: Mapped[str] = mapped_column(Text, nullable=False)
    sport_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "distance_source IN ('gps','watch_estimate','pool','mixed','none')",
            name="activity_stats_distance_source_check",
        ),
        CheckConstraint(
            "quality IN ('ok','partial','suspect')", name="activity_stats_quality_check"
        ),
    )


class ActivitySplit(Base):
    __tablename__ = "activity_split"

    activity_id: Mapped[int] = _act_pk()
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    idx: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = _uid()
    unit_m: Mapped[float | None] = _real()
    start_offset_s: Mapped[float | None] = _real()
    distance_m: Mapped[float | None] = _real()
    timer_s: Mapped[float | None] = _real()
    pace_s_km: Mapped[float | None] = _real()
    speed_kmh: Mapped[float | None] = _real()
    pace_s_100m: Mapped[float | None] = _real()
    elev_gain_m: Mapped[float | None] = _real()
    elev_loss_m: Mapped[float | None] = _real()
    hr_min: Mapped[int | None] = _small()
    hr_median: Mapped[int | None] = _small()
    hr_max: Mapped[int | None] = _small()
    hr_avg: Mapped[int | None] = _small()
    cadence_avg: Mapped[float | None] = _real()
    power_avg_w: Mapped[float | None] = _real()
    is_partial: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    lap_intensity: Mapped[str | None] = mapped_column(Text)
    lap_trigger: Mapped[str | None] = mapped_column(Text)
    wkt_step_index: Mapped[int | None] = _small()
    swim_lengths: Mapped[int | None] = _small()
    swolf: Mapped[float | None] = _real()
    quality: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint("kind IN ('distance','lap')", name="activity_split_kind_check"),
    )


class ActivityBestEffort(Base):
    __tablename__ = "activity_best_effort"

    activity_id: Mapped[int] = _act_pk()
    distance_key: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[uuid.UUID] = _uid()
    distance_m: Mapped[float] = mapped_column(REAL, nullable=False)
    duration_s: Mapped[float] = mapped_column(REAL, nullable=False)
    start_offset_s: Mapped[float] = mapped_column(REAL, nullable=False)
    start_km: Mapped[float] = mapped_column(REAL, nullable=False)
    hr_avg: Mapped[int | None] = _small()
    quality: Mapped[str] = mapped_column(Text, nullable=False)


class ActivityStepResult(Base):
    __tablename__ = "activity_step_result"

    activity_id: Mapped[int] = _act_pk()
    exec_idx: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = _uid()
    wkt_step_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    repeat_iteration: Mapped[int | None] = _small()
    step_type: Mapped[str] = mapped_column(Text, nullable=False)
    step_note: Mapped[str | None] = mapped_column(Text)
    planned_end: Mapped[str | None] = mapped_column(Text)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_low: Mapped[float | None] = _real()
    target_high: Mapped[float | None] = _real()
    target_source: Mapped[str | None] = mapped_column(Text)
    secondary_type: Mapped[str | None] = mapped_column(Text)
    secondary_low: Mapped[float | None] = _real()
    secondary_high: Mapped[float | None] = _real()
    timer_s: Mapped[float | None] = _real()
    distance_m: Mapped[float | None] = _real()
    avg_pace_s_km: Mapped[float | None] = _real()
    avg_hr: Mapped[float | None] = _real()
    hr_in_target_pct: Mapped[float | None] = _real()
    avg_cadence: Mapped[float | None] = _real()
    avg_power_w: Mapped[float | None] = _real()
    hit: Mapped[bool | None] = mapped_column(Boolean)
    secondary_hit: Mapped[bool | None] = mapped_column(Boolean)

    __table_args__ = (
        CheckConstraint(
            "target_source IN ('fit', 'api', 'unclear', 'none')",
            name="activity_step_result_target_source_check",
        ),
    )


class HrBucketSecondsDaily(Base):
    __tablename__ = "hr_bucket_seconds_daily"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    bpm_bucket: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    seconds: Mapped[int] = mapped_column(BigInteger, nullable=False)


class WellnessDailyStats(Base):
    __tablename__ = "wellness_daily_stats"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    metric_id: Mapped[int] = mapped_column(
        ForeignKey("metric_def.id", ondelete="RESTRICT"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    avg_value: Mapped[float] = mapped_column(Float, nullable=False)
    min_value: Mapped[float] = mapped_column(Float, nullable=False)
    max_value: Mapped[float] = mapped_column(Float, nullable=False)
    sample_count: Mapped[int] = mapped_column(BigInteger, nullable=False)


class MetricDailyValue(Base):
    __tablename__ = "metric_daily_value"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    # formula IDs from MetricRegistry (e.g. 'ctl', 'acwr'), not a metric_def FK --
    # these are derived metrics, not raw ingested ones
    metric_id: Mapped[str] = mapped_column(Text, primary_key=True)
    variant_id: Mapped[str] = mapped_column(Text, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    # NULL for multi-stat metrics (e.g. training_load's CTL/ATL/TSB dict) -- only
    # scalar formula outputs get a daily series in this table
    value: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(Text, nullable=False)


class CustomMetricDefinition(Base):
    __tablename__ = "custom_metric_definition"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    expression: Mapped[str] = mapped_column(Text, nullable=False)
    # 'agent' rows are written by CustomMetricRepository directly, never through the
    # client-facing router -- same spoof-proofing pattern as agent_memory.source
    created_by: Mapped[str] = mapped_column(Text, nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "code", name="uq_custom_metric_definition"),
        CheckConstraint(
            "created_by IN ('user', 'agent')", name="custom_metric_definition_created_by_check"
        ),
    )


class Conversation(Base):
    __tablename__ = "conversation"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    # first user message, truncated -- used as the label in the conversation list
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    compacted_through_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class ConversationMessage(Base):
    __tablename__ = "conversation_message"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # ordering key -- see the migration for why created_at alone isn't deterministic
    seq: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), nullable=False, unique=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False
    )
    # redundant to conversation.user_id, but needed directly here so this table's
    # own RLS policy doesn't need a subquery/join
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    # plain text for user/assistant; JSON tool-result payload (as text) for role='tool'
    content: Mapped[str | None] = mapped_column(Text)
    # tool calls the model requested this turn, if any -- null for role='user'/'tool'
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    # the id of the specific tool_call this result answers -- only set for role='tool',
    # required to correctly replay tool/assistant pairing back to the LLM on a later turn
    tool_call_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'tool')", name="conversation_message_role_check"
        ),
    )


class UserDashboardTile(Base):
    __tablename__ = "user_dashboard_tile"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    module_id: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Plan(Base):
    __tablename__ = "plan"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    goal_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('draft', 'committed', 'abandoned')", name="plan_status_check"),
    )


class PlanBlock(Base):
    __tablename__ = "plan_block"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plan.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    workout_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_trimp: Mapped[float | None] = mapped_column(Float)
    calendar_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calendar_event.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="planned")

    __table_args__ = (
        CheckConstraint(
            "workout_type IN ('long_run', 'hard', 'easy', 'rest')",
            name="plan_block_workout_type_check",
        ),
        CheckConstraint("status IN ('planned', 'done', 'skipped')", name="plan_block_status_check"),
    )


class DailySummary(Base):
    __tablename__ = "daily_summary"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    summary_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    raw_payload_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_payload.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "day", "summary_type", name="uq_daily_summary"),
    )


class Goal(Base):
    __tablename__ = "goal"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # free-text unit ("min", "km", "kg", ...) instead of an enum -- goal
    # shapes vary too much (race time, distance, weight, ...) to lock down
    target_value: Mapped[float | None] = mapped_column(Float)
    target_unit: Mapped[str | None] = mapped_column(String(32))
    target_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('active', 'completed', 'abandoned')", name="goal_status_check"),
    )


class AgentMemory(Base):
    __tablename__ = "agent_memory"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 'agent' entries are auto-written (shown with an undo affordance when written);
    # 'user' entries were added/edited by hand on the memory management page
    source: Mapped[str] = mapped_column(Text, nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("source IN ('user', 'agent')", name="agent_memory_source_check"),
    )

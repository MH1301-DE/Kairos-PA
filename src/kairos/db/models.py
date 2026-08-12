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
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
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

    __table_args__ = (
        UniqueConstraint(
            "user_id", "connector", "kind", "window_start", "content_hash",
            name="uq_raw_payload",
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
    # part of composite PK: Timescale needs the partitioning column in every PK/unique constraint
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, primary_key=True
    )
    value: Mapped[float] = mapped_column(Float, nullable=False)
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
    activity_type: Mapped[str | None] = mapped_column(Text)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    distance_m: Mapped[float | None] = mapped_column(Float)
    duration_s: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[int | None] = mapped_column(SmallInteger)
    max_hr: Mapped[int | None] = mapped_column(SmallInteger)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)
    calories: Mapped[int | None] = mapped_column(Integer)
    # future: path to raw FIT bytes in object store
    fit_object_key: Mapped[str | None] = mapped_column(Text)
    data_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_source.id", ondelete="SET NULL")
    )
    raw_payload_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_payload.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "external_id", name="uq_activity"),
    )


class ActivityRecord(Base):
    __tablename__ = "activity_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    activity_id: Mapped[int] = mapped_column(
        ForeignKey("activity.id", ondelete="CASCADE"),
        nullable=False,
    )
    # part of composite PK: Timescale needs the partitioning column in every PK/unique constraint
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, primary_key=True
    )
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    raw_payload_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_payload.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "user_id", "activity_id", "recorded_at", "metric", name="uq_activity_record"
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

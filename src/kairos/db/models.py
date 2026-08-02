import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
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
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "status IN ('active','reauth_required','disabled','error')",
            name="connection_status_check",
        ),
        UniqueConstraint("user_id", "connector", "external_account", name="uq_connection"),
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
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, primary_key=True
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

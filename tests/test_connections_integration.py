from __future__ import annotations

import types
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.crypto import encrypt, generate_dek, kek_from_settings, wrap_dek
from kairos.config import settings
from kairos.db.models import Connection
from kairos.routers import sync as sync_module
from kairos.routers.connections import _store_connection


async def _insert_user(session: AsyncSession, user_id: UUID, email: str, sub: str) -> bytes:
    kek = kek_from_settings(settings.kairos_kek)
    dek = generate_dek()
    await session.execute(
        text(
            """
            INSERT INTO app_user
                (id, email, display_name, google_sub, home_timezone, role, dek_wrapped)
            VALUES (:id, :email, :name, :sub, 'UTC', 'user', :dek)
            """
        ),
        {
            "id": str(user_id),
            "email": email,
            "name": "Test",
            "sub": sub,
            "dek": wrap_dek(dek, kek),
        },
    )
    return dek


@pytest.mark.asyncio
async def test_reonboarding_other_garmin_account_disables_previous_connection(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id, "reonboard@test.com", "sub-reonboard")

    await _store_connection(session, user_id, "account-a@garmin.com", '{"token":"A"}')
    await session.commit()
    await _store_connection(session, user_id, "account-b@garmin.com", '{"token":"B"}')
    await session.commit()

    rows = (
        await session.execute(
            select(Connection)
            .where(Connection.user_id == user_id, Connection.connector == "garmin")
            .order_by(Connection.external_account)
        )
    ).scalars().all()

    assert len(rows) == 2
    by_account = {r.external_account: r.status for r in rows}
    assert by_account == {
        "account-a@garmin.com": "disabled",
        "account-b@garmin.com": "active",
    }

    active = [r for r in rows if r.status == "active"]
    assert len(active) == 1
    assert active[0].external_account == "account-b@garmin.com"


@pytest.mark.asyncio
async def test_reconnecting_same_garmin_account_keeps_single_active_row(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id, "same-account@test.com", "sub-same-account")

    await _store_connection(session, user_id, "same@garmin.com", '{"token":"1"}')
    await session.commit()
    await _store_connection(session, user_id, "same@garmin.com", '{"token":"2"}')
    await session.commit()

    rows = (
        await session.execute(
            select(Connection).where(
                Connection.user_id == user_id, Connection.connector == "garmin"
            )
        )
    ).scalars().all()

    assert len(rows) == 1
    assert rows[0].status == "active"


class _FakeGarmin:
    def __init__(self) -> None:
        self.login_token: str | None = None

    def login(self, token_json: str) -> None:
        self.login_token = token_json


@pytest.mark.asyncio
async def test_build_garmin_client_picks_newest_of_duplicate_connections(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    dek = await _insert_user(session, user_id, "dupe-conn@test.com", "sub-dupe-conn")

    # duplicate active rows can pre-exist from before the write-side fix
    session.add(
        Connection(
            user_id=user_id,
            connector="garmin",
            external_account="old@garmin.com",
            status="active",
            credentials_enc=encrypt(b'{"token":"OLD"}', dek),
            connected_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    session.add(
        Connection(
            user_id=user_id,
            connector="garmin",
            external_account="new@garmin.com",
            status="active",
            credentials_enc=encrypt(b'{"token":"NEW"}', dek),
            connected_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
    )
    await session.commit()

    fake = _FakeGarmin()
    monkeypatch.setattr(
        sync_module,
        "importlib",
        types.SimpleNamespace(
            import_module=lambda name: types.SimpleNamespace(Garmin=lambda: fake)
        ),
    )

    client = await sync_module._build_garmin_client(session, user_id)

    assert client is fake
    assert fake.login_token == '{"token":"NEW"}'

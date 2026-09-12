from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.crypto import decrypt, generate_dek, kek_from_settings, unwrap_dek, wrap_dek
from kairos.config import settings
from kairos.db.models import AppUser, Connection, UserSetting
from kairos.routers.connections import _store_llm_connection


async def _insert_user_with_dek(session: AsyncSession, user_id: UUID) -> None:
    kek = kek_from_settings(settings.kairos_kek)
    dek = generate_dek()
    await session.execute(
        text(
            "INSERT INTO app_user "
            "(id, email, display_name, google_sub, home_timezone, role, dek_wrapped) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user', :dek)"
        ),
        {
            "id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}",
            "dek": wrap_dek(dek, kek),
        },
    )


async def _insert_user_without_dek(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )


@pytest.mark.asyncio
async def test_store_llm_connection_encrypts_and_syncs_user_setting(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user_with_dek(session, user_id)
    await session.commit()

    await _store_llm_connection(session, user_id, "anthropic/claude-sonnet-5", "sk-test-key-1")
    await session.commit()

    conn = (
        await session.execute(
            select(Connection).where(
                Connection.user_id == user_id, Connection.connector == "llm_provider"
            )
        )
    ).scalar_one()
    assert conn.status == "active"
    assert conn.external_account == "anthropic/claude-sonnet-5"
    assert conn.credentials_enc != b"sk-test-key-1"  # must be encrypted, not raw

    user_row = (
        await session.execute(select(AppUser).where(AppUser.id == user_id))
    ).scalar_one()
    kek = kek_from_settings(settings.kairos_kek)
    dek = unwrap_dek(user_row.dek_wrapped, kek)
    assert decrypt(conn.credentials_enc, dek).decode() == "sk-test-key-1"

    setting = (
        await session.execute(select(UserSetting).where(UserSetting.user_id == user_id))
    ).scalar_one()
    assert setting.llm_model == "anthropic/claude-sonnet-5"


@pytest.mark.asyncio
async def test_store_llm_connection_generates_a_dek_if_missing(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user_without_dek(session, user_id)
    await session.commit()

    await _store_llm_connection(session, user_id, "anthropic/claude-sonnet-5", "sk-test-key-2")
    await session.commit()

    user_row = (
        await session.execute(select(AppUser).where(AppUser.id == user_id))
    ).scalar_one()
    assert user_row.dek_wrapped is not None


@pytest.mark.asyncio
async def test_reconfiguring_a_different_model_disables_the_previous_connection(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user_with_dek(session, user_id)
    await session.commit()

    await _store_llm_connection(session, user_id, "anthropic/claude-sonnet-5", "sk-a")
    await session.commit()
    await _store_llm_connection(session, user_id, "openai/gpt-5", "sk-b")
    await session.commit()

    rows = (
        await session.execute(
            select(Connection).where(
                Connection.user_id == user_id, Connection.connector == "llm_provider"
            )
        )
    ).scalars().all()
    by_model = {r.external_account: r.status for r in rows}
    assert by_model == {"anthropic/claude-sonnet-5": "disabled", "openai/gpt-5": "active"}

    setting = (
        await session.execute(select(UserSetting).where(UserSetting.user_id == user_id))
    ).scalar_one()
    assert setting.llm_model == "openai/gpt-5"

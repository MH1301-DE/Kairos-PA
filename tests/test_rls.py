import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.models import AppUser
from kairos.db.rls import install_rls_listener


@pytest.mark.asyncio
async def test_rls_isolates_users(session: AsyncSession, app_session: AsyncSession) -> None:
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()

    # Insert two users via the superuser session (superuser bypasses RLS → no WITH CHECK blocks)
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) VALUES "
            "(:id1, :e1, :n1, :s1, 'UTC', 'user'), (:id2, :e2, :n2, :s2, 'UTC', 'user')"
        ),
        {
            "id1": str(user_a_id), "e1": "a@test.com", "n1": "A", "s1": "sub_a",
            "id2": str(user_b_id), "e2": "b@test.com", "n2": "B", "s2": "sub_b",
        },
    )
    await session.commit()

    # app_session connects as kairos_app (NOSUPERUSER) → RLS is enforced
    install_rls_listener(app_session, user_a_id)

    result = await app_session.execute(select(AppUser))
    users = result.scalars().all()

    assert len(users) == 1, f"Expected 1 user, got {len(users)}: {[u.email for u in users]}"
    assert users[0].id == user_a_id

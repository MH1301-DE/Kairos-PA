from __future__ import annotations

from dataclasses import dataclass

import pytest

from kairos.connectors.garmin.client import (
    AuthTokens,
    BackendInvalidCredentials,
    BackendMfaRequired,
    BackendUnavailable,
    GarminAuthBackend,
    GarminClient,
    InvalidCredentials,
    NeedsMfaToken,
    UpstreamUnavailable,
)


@dataclass
class FakeBackend(GarminAuthBackend):
    require_mfa: bool = False
    fail_invalid_credentials: bool = False
    fail_unavailable_on_refresh: bool = False

    login_calls: list[tuple[str, str, str | None]] | None = None
    refresh_calls: list[str] | None = None

    def __post_init__(self) -> None:
        if self.login_calls is None:
            self.login_calls = []
        if self.refresh_calls is None:
            self.refresh_calls = []

    def login(self, username: str, password: str, mfa_token: str | None) -> AuthTokens:
        assert self.login_calls is not None
        self.login_calls.append((username, password, mfa_token))

        if self.fail_invalid_credentials:
            raise BackendInvalidCredentials()
        if self.require_mfa and mfa_token is None:
            raise BackendMfaRequired()

        return AuthTokens(access_token="access-1", refresh_token="refresh-1")

    def refresh_token(self, refresh_token: str) -> AuthTokens:
        assert self.refresh_calls is not None
        self.refresh_calls.append(refresh_token)

        if self.fail_unavailable_on_refresh:
            raise BackendUnavailable()

        return AuthTokens(access_token="access-2", refresh_token="refresh-2")


class LoginUnavailableBackend(GarminAuthBackend):
    def login(self, username: str, password: str, mfa_token: str | None) -> AuthTokens:
        del username, password, mfa_token
        raise BackendUnavailable()

    def refresh_token(self, refresh_token: str) -> AuthTokens:
        del refresh_token
        return AuthTokens(access_token="access-2", refresh_token="refresh-2")


class RefreshInvalidCredentialsBackend(GarminAuthBackend):
    def login(self, username: str, password: str, mfa_token: str | None) -> AuthTokens:
        del username, password, mfa_token
        return AuthTokens(access_token="access-1", refresh_token="refresh-1")

    def refresh_token(self, refresh_token: str) -> AuthTokens:
        del refresh_token
        raise BackendInvalidCredentials()


class RefreshMfaRequiredBackend(GarminAuthBackend):
    def login(self, username: str, password: str, mfa_token: str | None) -> AuthTokens:
        del username, password, mfa_token
        return AuthTokens(access_token="access-1", refresh_token="refresh-1")

    def refresh_token(self, refresh_token: str) -> AuthTokens:
        del refresh_token
        raise BackendMfaRequired()


class TwoStepMfaThenUnavailableBackend(GarminAuthBackend):
    def __init__(self) -> None:
        self.login_calls: list[tuple[str, str, str | None]] = []

    def login(self, username: str, password: str, mfa_token: str | None) -> AuthTokens:
        self.login_calls.append((username, password, mfa_token))
        if mfa_token is None:
            raise BackendMfaRequired()
        raise BackendUnavailable()

    def refresh_token(self, refresh_token: str) -> AuthTokens:
        del refresh_token
        return AuthTokens(access_token="access-2", refresh_token="refresh-2")


def test_login_without_mfa() -> None:
    backend = FakeBackend()
    client = GarminClient(backend=backend)

    tokens = client.login(username="user", password="pass")

    assert tokens == AuthTokens(access_token="access-1", refresh_token="refresh-1")
    assert backend.login_calls == [("user", "pass", None)]


def test_login_with_dynamic_mfa_callback_retries_once() -> None:
    backend = FakeBackend(require_mfa=True)
    client = GarminClient(backend=backend)

    tokens = client.login(
        username="user",
        password="pass",
        mfa_callback=lambda: "654321",
    )

    assert tokens == AuthTokens(access_token="access-1", refresh_token="refresh-1")
    assert backend.login_calls == [
        ("user", "pass", None),
        ("user", "pass", "654321"),
    ]


def test_refresh_token_path() -> None:
    backend = FakeBackend()
    client = GarminClient(backend=backend)

    tokens = client.refresh_token(refresh_token="refresh-1")

    assert tokens == AuthTokens(access_token="access-2", refresh_token="refresh-2")
    assert backend.refresh_calls == ["refresh-1"]


def test_login_maps_invalid_credentials() -> None:
    backend = FakeBackend(fail_invalid_credentials=True)
    client = GarminClient(backend=backend)

    with pytest.raises(InvalidCredentials):
        client.login(username="user", password="bad-pass")


def test_login_raises_needs_mfa_token_without_callback() -> None:
    backend = FakeBackend(require_mfa=True)
    client = GarminClient(backend=backend)

    with pytest.raises(NeedsMfaToken):
        client.login(username="user", password="pass")


def test_refresh_token_maps_upstream_unavailable() -> None:
    backend = FakeBackend(fail_unavailable_on_refresh=True)
    client = GarminClient(backend=backend)

    with pytest.raises(UpstreamUnavailable):
        client.refresh_token(refresh_token="refresh-1")


def test_login_maps_upstream_unavailable() -> None:
    backend = LoginUnavailableBackend()
    client = GarminClient(backend=backend)

    with pytest.raises(UpstreamUnavailable):
        client.login(username="user", password="pass")


def test_login_retry_maps_upstream_unavailable() -> None:
    backend = TwoStepMfaThenUnavailableBackend()
    client = GarminClient(backend=backend)

    with pytest.raises(UpstreamUnavailable):
        client.login(username="user", password="pass", mfa_callback=lambda: "123456")

    assert backend.login_calls == [
        ("user", "pass", None),
        ("user", "pass", "123456"),
    ]


def test_login_raises_needs_mfa_if_callback_returns_none() -> None:
    backend = FakeBackend(require_mfa=True)
    client = GarminClient(backend=backend)

    with pytest.raises(NeedsMfaToken):
        client.login(username="user", password="pass", mfa_callback=lambda: None)


def test_refresh_token_maps_invalid_credentials() -> None:
    backend = RefreshInvalidCredentialsBackend()
    client = GarminClient(backend=backend)

    with pytest.raises(InvalidCredentials):
        client.refresh_token(refresh_token="refresh-1")


def test_refresh_token_maps_needs_mfa_token() -> None:
    backend = RefreshMfaRequiredBackend()
    client = GarminClient(backend=backend)

    with pytest.raises(NeedsMfaToken):
        client.refresh_token(refresh_token="refresh-1")

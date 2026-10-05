from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from kairos.connectors.garmin.client import (
    BackendInvalidCredentials,
    BackendMfaRequired,
    BackendUnavailable,
    GarminClient,
    GarminConnectBackend,
    InvalidCredentials,
    NeedsMfaToken,
    UpstreamUnavailable,
)

# ---------------------------------------------------------------------------
# Fake garminconnect module
# ---------------------------------------------------------------------------

_TOKEN_JSON = json.dumps(
    {
        "access_token": "access-abc",
        "refresh_token": "refresh-abc",
        "token_type": "Bearer",
        "expires_in": 3600,
        # padded so len > 513 for inline-token branch in refresh_token()
        "padding": "x" * 600,
    }
)


@dataclass
class FakeGarminClient:
    """Mimics garminconnect's internal client object."""

    dumped_dir: str | None = None
    skip_strategies: set[str] | None = None

    def dump(self, directory: str) -> None:
        self.dumped_dir = directory
        (Path(directory) / "garmin_tokens.json").write_text(_TOKEN_JSON)

    def load(self, path: str) -> None:
        pass

    def loads(self, token: str) -> None:
        pass


@dataclass
class FakeGarmin:
    """Mimics garminconnect.Garmin."""

    email: str | None = None
    password: str | None = None
    return_on_mfa: bool = False
    prompt_mfa: object = None

    require_mfa: bool = False
    fail_auth: bool = False
    fail_rate: bool = False
    fail_unavailable: bool = False

    client: FakeGarminClient = field(default_factory=FakeGarminClient)

    _mfa_state: dict[str, object] = field(default_factory=lambda: {"state": "opaque"})

    def login(self, tokenstore: str | None = None) -> tuple[str | None, object]:
        if self.fail_auth:
            raise FakeAuthError("bad credentials")
        if self.fail_rate:
            raise FakeRateError("429")
        if self.fail_unavailable:
            raise FakeConnectionError("connection error")
        if self.require_mfa and self.return_on_mfa:
            return "needs_mfa", self._mfa_state
        return None, None

    def resume_login(self, client_state: object, mfa_code: str) -> tuple[None, None]:
        if mfa_code != "123456":
            raise FakeAuthError("invalid MFA code")
        return None, None


class FakeAuthError(Exception):
    pass


class FakeRateError(Exception):
    pass


class FakeConnectionError(Exception):
    pass


class FakeModule:
    GarminConnectAuthenticationError = FakeAuthError
    GarminConnectTooManyRequestsError = FakeRateError
    GarminConnectConnectionError = FakeConnectionError

    def __init__(self, **kwargs: object) -> None:
        self._defaults = kwargs
        self.last_instance: FakeGarmin | None = None

    def Garmin(self, **kwargs: object) -> FakeGarmin:
        merged = {**self._defaults, **kwargs}
        valid = FakeGarmin.__dataclass_fields__
        instance = FakeGarmin(**{k: v for k, v in merged.items() if k in valid})
        self.last_instance = instance
        return instance


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_backend(**defaults: object) -> GarminConnectBackend:
    return GarminConnectBackend(garmin_module=FakeModule(**defaults))


# ---------------------------------------------------------------------------
# GarminConnectBackend – login
# ---------------------------------------------------------------------------

def test_login_no_mfa() -> None:
    backend = _make_backend()
    tokens = backend.login("user@example.com", "secret", mfa_token=None)

    assert tokens.refresh_token == _TOKEN_JSON
    assert tokens.access_token == ""


def test_login_with_mfa_token_provided() -> None:
    backend = _make_backend(require_mfa=True)
    tokens = backend.login("user@example.com", "secret", mfa_token="123456")

    assert tokens.refresh_token == _TOKEN_JSON


def test_login_mfa_required_raises_when_no_token() -> None:
    backend = _make_backend(require_mfa=True)

    with pytest.raises(BackendMfaRequired):
        backend.login("user@example.com", "secret", mfa_token=None)


def test_login_invalid_credentials_mapped() -> None:
    backend = _make_backend(fail_auth=True)

    with pytest.raises(BackendInvalidCredentials):
        backend.login("user@example.com", "wrong", mfa_token=None)


def test_login_rate_limit_mapped_to_unavailable() -> None:
    backend = _make_backend(fail_rate=True)

    with pytest.raises(BackendUnavailable):
        backend.login("user@example.com", "secret", mfa_token=None)


def test_login_connection_error_mapped_to_unavailable() -> None:
    backend = _make_backend(fail_unavailable=True)

    with pytest.raises(BackendUnavailable):
        backend.login("user@example.com", "secret", mfa_token=None)


def test_login_uses_single_hardened_strategy_not_cascade() -> None:
    """Regression test: a real login must try exactly one strategy (widget+cffi),
    never the full 5-strategy cascade — each extra strategy is an extra request
    against Garmin, and trying several per click is what got a real IP
    Cloudflare-banned (Error 1015) during manual testing of this project.
    mobile+cffi is skipped since Garmin 429s its clientId from every network."""
    backend = _make_backend()
    tokens = backend.login("user@example.com", "secret", mfa_token=None)

    assert tokens.refresh_token == _TOKEN_JSON
    # the FakeGarmin instance backend.login() constructed is discarded after the
    # call, so inspect it through the module's last-built instance instead
    built = backend._module.last_instance
    assert built is not None
    assert built.client.skip_strategies == {
        "mobile+cffi",
        "mobile+requests",
        "portal+cffi",
        "portal+requests",
    }


# ---------------------------------------------------------------------------
# GarminConnectBackend – refresh_token
# ---------------------------------------------------------------------------

def test_refresh_token_inline_blob() -> None:
    """Token JSON > 513 chars is passed inline to garminconnect."""
    backend = _make_backend()
    tokens = backend.refresh_token(_TOKEN_JSON)

    assert tokens.refresh_token == _TOKEN_JSON


def test_refresh_token_short_written_to_file() -> None:
    """Short token blobs are written to a temp file first."""
    short_token = json.dumps({"access_token": "x", "refresh_token": "y"})
    assert len(short_token) <= 513

    backend = _make_backend()
    tokens = backend.refresh_token(short_token)

    assert tokens.refresh_token == _TOKEN_JSON


def test_refresh_invalid_credentials_mapped() -> None:
    backend = _make_backend(fail_auth=True)

    with pytest.raises(BackendInvalidCredentials):
        backend.refresh_token(_TOKEN_JSON)


# ---------------------------------------------------------------------------
# GarminClient MFA retry layer (unchanged from previous design)
# ---------------------------------------------------------------------------

def test_garmin_client_calls_mfa_callback_and_retries() -> None:
    backend = _make_backend(require_mfa=True)
    client = GarminClient(backend=backend)

    tokens = client.login("u", "p", mfa_callback=lambda: "123456")

    assert tokens.refresh_token == _TOKEN_JSON


def test_garmin_client_raises_needs_mfa_without_callback() -> None:
    backend = _make_backend(require_mfa=True)
    client = GarminClient(backend=backend)

    with pytest.raises(NeedsMfaToken):
        client.login("u", "p")


def test_garmin_client_maps_invalid_credentials() -> None:
    backend = _make_backend(fail_auth=True)
    client = GarminClient(backend=backend)

    with pytest.raises(InvalidCredentials):
        client.login("u", "p")


def test_garmin_client_maps_unavailable() -> None:
    backend = _make_backend(fail_unavailable=True)
    client = GarminClient(backend=backend)

    with pytest.raises(UpstreamUnavailable):
        client.login("u", "p")


def test_garmin_client_refresh_token_maps_invalid_credentials() -> None:
    backend = _make_backend(fail_auth=True)
    client = GarminClient(backend=backend)

    with pytest.raises(InvalidCredentials):
        client.refresh_token(_TOKEN_JSON)


# ---------------------------------------------------------------------------
# Missing garminconnect package → BackendUnavailable
# ---------------------------------------------------------------------------

def test_import_failure_raises_unavailable_on_login() -> None:
    backend = GarminConnectBackend(garmin_module=None)
    # Force import failure without an actual missing package
    backend._module = None
    backend._import_error = ModuleNotFoundError("garminconnect")

    with pytest.raises(BackendUnavailable):
        backend.login("u", "p", mfa_token=None)

from __future__ import annotations

import importlib
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, Protocol


@dataclass(frozen=True)
class AuthTokens:
    # access_token unused for garminconnect; refresh_token holds the full token JSON blob.
    access_token: str
    refresh_token: str


class NeedsMfaToken(Exception):
    pass


class InvalidCredentials(Exception):
    pass


class UpstreamUnavailable(Exception):
    pass


class BackendMfaRequired(Exception):
    pass


class BackendInvalidCredentials(Exception):
    pass


class BackendUnavailable(Exception):
    pass


class GarminAuthBackend(Protocol):
    def login(self, username: str, password: str, mfa_token: str | None) -> AuthTokens:
        ...

    def refresh_token(self, refresh_token: str) -> AuthTokens:
        ...


# garminconnect treats a tokenstore string as inline data when len > 512.
_MIN_INLINE_TOKEN_LEN = 513

# garminconnect's Client.login() cascades through up to 5 login strategies
# (mobile+cffi, mobile+requests, widget+cffi, portal+cffi, portal+requests) by
# default, trying each in turn on any non-credential failure. That means one
# click can fire up to 5 requests at Garmin's SSO endpoints, and a run of mixed
# 429s/challenge-page failures across strategies gets misclassified by the
# library's own error-mapping as "wrong password" (a real, reproduced incident:
# repeated manual login attempts against a real account triggered a Cloudflare
# Error 1015 temporary IP ban on sso.garmin.com, and 401s were returned to the
# user even though the credentials were never actually wrong).
# Only widget+cffi: Garmin 429s the mobile clientId from every network since 2026-10.
_SKIPPED_LOGIN_STRATEGIES = frozenset(
    {"mobile+cffi", "mobile+requests", "portal+cffi", "portal+requests"}
)


def _harden_to_single_strategy(garmin: Any) -> None:
    garmin.client.skip_strategies = set(_SKIPPED_LOGIN_STRATEGIES)


class GarminConnectBackend:
    def __init__(self, garmin_module: Any = None) -> None:
        self._module: Any = garmin_module
        self._import_error: Exception | None = None
        if self._module is None:
            self._module = self._import_default_module()

    def _import_default_module(self) -> Any:
        try:
            return importlib.import_module("garminconnect")
        except Exception as exc:
            self._import_error = exc
            return None

    def _require_module(self) -> Any:
        if self._module is None:
            raise BackendUnavailable() from self._import_error
        return self._module

    def login(self, username: str, password: str, mfa_token: str | None) -> AuthTokens:
        mod = self._require_module()
        try:
            garmin = mod.Garmin(email=username, password=password, return_on_mfa=True)
            _harden_to_single_strategy(garmin)
            with tempfile.TemporaryDirectory() as tmpdir:
                mfa_status, client_state = garmin.login(tmpdir)
                if mfa_status == "needs_mfa":
                    if mfa_token is None:
                        raise BackendMfaRequired()
                    garmin.resume_login(client_state, mfa_token)
                # return_on_mfa=True never auto-saves; always dump explicitly.
                garmin.client.dump(tmpdir)
                token_str = _read_token_file(tmpdir)
            return AuthTokens(access_token="", refresh_token=token_str)
        except BackendMfaRequired:
            raise
        except Exception as exc:
            _raise_mapped(mod, exc)

    def refresh_token(self, refresh_token: str) -> AuthTokens:
        mod = self._require_module()
        try:
            garmin = mod.Garmin()
            _harden_to_single_strategy(garmin)
            if len(refresh_token) > _MIN_INLINE_TOKEN_LEN:
                tokenstore: str = refresh_token
                with tempfile.TemporaryDirectory() as tmpdir:
                    garmin.login(tokenstore)
                    garmin.client.dump(tmpdir)
                    token_str = _read_token_file(tmpdir)
            else:
                with tempfile.TemporaryDirectory() as tmpdir:
                    (Path(tmpdir) / "garmin_tokens.json").write_text(refresh_token)
                    garmin.login(tmpdir)
                    garmin.client.dump(tmpdir)
                    token_str = _read_token_file(tmpdir)
            return AuthTokens(access_token="", refresh_token=token_str)
        except Exception as exc:
            _raise_mapped(mod, exc)


def _read_token_file(directory: str) -> str:
    token_path = Path(directory) / "garmin_tokens.json"
    if token_path.exists():
        return token_path.read_text()
    for p in Path(directory).glob("*.json"):
        return p.read_text()
    raise BackendUnavailable()


def _raise_mapped(mod: Any, exc: Exception) -> NoReturn:
    auth_exc = getattr(mod, "GarminConnectAuthenticationError", None)
    rate_exc = getattr(mod, "GarminConnectTooManyRequestsError", None)
    if auth_exc is not None and isinstance(exc, auth_exc):
        raise BackendInvalidCredentials() from exc
    if rate_exc is not None and isinstance(exc, rate_exc):
        raise BackendUnavailable() from exc
    raise BackendUnavailable() from exc


MfaCallback = Callable[[], str | None]


class GarminClient:
    def __init__(self, backend: GarminAuthBackend) -> None:
        self._backend = backend

    def login(
        self,
        username: str,
        password: str,
        mfa_token: str | None = None,
        mfa_callback: MfaCallback | None = None,
    ) -> AuthTokens:
        try:
            return self._backend.login(username=username, password=password, mfa_token=mfa_token)
        except BackendMfaRequired as exc:
            retry_mfa_token = mfa_token
            if retry_mfa_token is None and mfa_callback is not None:
                retry_mfa_token = mfa_callback()
            if retry_mfa_token is None:
                raise NeedsMfaToken() from exc

            try:
                return self._backend.login(
                    username=username,
                    password=password,
                    mfa_token=retry_mfa_token,
                )
            except BackendMfaRequired as inner_exc:
                raise NeedsMfaToken() from inner_exc
            except BackendInvalidCredentials as inner_exc:
                raise InvalidCredentials() from inner_exc
            except BackendUnavailable as inner_exc:
                raise UpstreamUnavailable() from inner_exc
        except BackendInvalidCredentials as exc:
            raise InvalidCredentials() from exc
        except BackendUnavailable as exc:
            raise UpstreamUnavailable() from exc

    def refresh_token(self, refresh_token: str) -> AuthTokens:
        try:
            return self._backend.refresh_token(refresh_token=refresh_token)
        except BackendMfaRequired as exc:
            raise NeedsMfaToken() from exc
        except BackendInvalidCredentials as exc:
            raise InvalidCredentials() from exc
        except BackendUnavailable as exc:
            raise UpstreamUnavailable() from exc

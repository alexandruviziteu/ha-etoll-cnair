"""Teste pentru clientul API (HTTP simulat; fără rețea reală)."""

from __future__ import annotations

from collections import deque
from typing import Any
from unittest.mock import AsyncMock

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.etoll_cnair.api import (
    EtollApi,
    EtollAuthError,
    EtollConnectionError,
    EtollError,
    EtollHttpError,
    EtollRateLimitError,
    _parse_retry_after,
)
from custom_components.etoll_cnair.const import TOKEN_URL, URL_TOLLS

from .conftest import PASSWORD, USERNAME

TOKEN_OK = {
    "access_token": "fake-access",
    "refresh_token": "fake-refresh",
    "expires_in": 300,
    "refresh_expires_in": 1800,
}


def _queue(*responses: dict[str, Any]):
    """side_effect care întoarce pe rând răspunsurile date (ultimul se repetă)."""
    pending = deque(responses)

    async def _effect(method: str, url: URL, data: Any):
        spec = pending.popleft() if len(pending) > 1 else pending[0]
        return AiohttpClientMockResponse(method, url, **spec)

    return _effect


@pytest.fixture
async def api(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> EtollApi:
    """Sesiunea trebuie creată după ce aioclient_mock a înlocuit conectorul."""
    return EtollApi(async_get_clientsession(hass), USERNAME, PASSWORD)


# ----------------------------------------------------------------- login
async def test_login_success(
    api: EtollApi, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(TOKEN_URL, json=TOKEN_OK)
    await api.login()
    assert aioclient_mock.call_count == 1


@pytest.mark.parametrize("status", [400, 401])
async def test_login_rejected_is_auth_error(
    api: EtollApi, aioclient_mock: AiohttpClientMocker, status: int
) -> None:
    aioclient_mock.post(TOKEN_URL, status=status, json={"error": "invalid_grant"})
    with pytest.raises(EtollAuthError):
        await api.login()


async def test_login_server_error_is_not_auth_error(
    api: EtollApi, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(TOKEN_URL, status=500)
    with pytest.raises(EtollError) as err:
        await api.login()
    assert not isinstance(err.value, EtollAuthError)


async def test_login_connection_error(
    api: EtollApi, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(TOKEN_URL, exc=aiohttp.ClientError("boom"))
    with pytest.raises(EtollConnectionError):
        await api.login()


# ------------------------------------------------------------ coduri HTTP
async def test_get_401_relogin_then_success(
    api: EtollApi, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(TOKEN_URL, json=TOKEN_OK)
    aioclient_mock.get(
        URL_TOLLS,
        side_effect=_queue(
            {"status": 401}, {"status": 200, "json": {"tolls": [{"a": 1}]}}
        ),
    )
    assert await api.get_tolls() == [{"a": 1}]
    # două autentificări: cea inițială și cea de după 401
    assert len([c for c in aioclient_mock.mock_calls if c[0].lower() == "post"]) == 2


async def test_get_401_twice_is_auth_error(
    api: EtollApi, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(TOKEN_URL, json=TOKEN_OK)
    aioclient_mock.get(URL_TOLLS, status=401)
    with pytest.raises(EtollAuthError):
        await api.get_tolls()


async def test_get_403_is_http_error_not_auth(
    api: EtollApi, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(TOKEN_URL, json=TOKEN_OK)
    aioclient_mock.get(URL_TOLLS, status=403, text="blocked")
    with pytest.raises(EtollHttpError) as err:
        await api.get_tolls()
    assert not isinstance(err.value, EtollAuthError)
    assert err.value.status == 403
    # fără retry și fără relogin pe 403
    assert len([c for c in aioclient_mock.mock_calls if c[0].lower() == "get"]) == 1
    assert len([c for c in aioclient_mock.mock_calls if c[0].lower() == "post"]) == 1


async def test_get_429_carries_retry_after(
    api: EtollApi, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(TOKEN_URL, json=TOKEN_OK)
    aioclient_mock.get(URL_TOLLS, status=429, headers={"Retry-After": "120"})
    with pytest.raises(EtollRateLimitError) as err:
        await api.get_tolls()
    assert err.value.retry_after == 120.0
    assert not isinstance(err.value, EtollAuthError)


async def test_get_429_without_header(
    api: EtollApi, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(TOKEN_URL, json=TOKEN_OK)
    aioclient_mock.get(URL_TOLLS, status=429)
    with pytest.raises(EtollRateLimitError) as err:
        await api.get_tolls()
    assert err.value.retry_after is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [("120", 120.0), ("0", 0.0), (None, None), ("Wed, 21 Oct 2026 07:28:00 GMT", None)],
)
def test_parse_retry_after(value: str | None, expected: float | None) -> None:
    assert _parse_retry_after(value) == expected


async def test_get_connection_error(
    api: EtollApi, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(TOKEN_URL, json=TOKEN_OK)
    aioclient_mock.get(URL_TOLLS, exc=aiohttp.ClientError("boom"))
    with pytest.raises(EtollConnectionError):
        await api.get_tolls()


# ------------------------------------------------------- fallback vehicule
async def test_get_vehicles_fallback_on_4xx(api: EtollApi) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_get(url: str, params: dict[str, Any] | None = None, **_: Any):
        calls.append(dict(params or {}))
        if "vehicleType" not in (params or {}):
            raise EtollHttpError(400, "bad param")
        return {"vehicles": [{"plateNumber": "AB00XYZ"}]}

    api._get = fake_get  # type: ignore[method-assign]
    assert await api.get_vehicles() == [{"plateNumber": "AB00XYZ"}]
    assert "vehicleType" not in calls[0]
    assert calls[1]["vehicleType"] == "CAR"


@pytest.mark.parametrize(
    "exc",
    [
        EtollHttpError(403),
        EtollRateLimitError(10),
        EtollHttpError(500),
        EtollConnectionError("down"),
    ],
)
async def test_get_vehicles_no_fallback_on_other_errors(
    api: EtollApi, exc: Exception
) -> None:
    api._get = AsyncMock(side_effect=exc)  # type: ignore[method-assign]
    with pytest.raises(type(exc)):
        await api.get_vehicles()
    assert api._get.await_count == 1


async def test_get_vehicles_auth_error_propagates(api: EtollApi) -> None:
    api._get = AsyncMock(side_effect=EtollAuthError("401"))  # type: ignore[method-assign]
    with pytest.raises(EtollAuthError):
        await api.get_vehicles()
    assert api._get.await_count == 1


# ---------------------------------------------------------------- paginare
async def test_cursor_pagination_follows_next_cursor(api: EtollApi) -> None:
    pages = deque(
        [
            {"tolls": [{"id": 1}], "nextCursor": "c2"},
            {"tolls": [{"id": 2}], "nextCursor": None},
        ]
    )
    seen: list[dict[str, Any]] = []

    async def fake_get(url: str, params: dict[str, Any] | None = None, **_: Any):
        seen.append(dict(params or {}))
        return pages.popleft()

    api._get = fake_get  # type: ignore[method-assign]
    assert await api.get_tolls() == [{"id": 1}, {"id": 2}]
    assert "cursor" not in seen[0]
    assert seen[1]["cursor"] == "c2"


async def test_cursor_pagination_capped_at_10_pages(api: EtollApi) -> None:
    api._get = AsyncMock(  # type: ignore[method-assign]
        return_value={"tolls": [{"id": 1}], "nextCursor": "again"}
    )
    assert len(await api.get_tolls()) == 10
    assert api._get.await_count == 10


async def test_invoices_pagination(api: EtollApi) -> None:
    pages = deque(
        [
            {"invoices": [{"n": 1}], "page": {"last": False}},
            {"invoices": [{"n": 2}], "page": {"last": True}},
        ]
    )
    api._get = AsyncMock(side_effect=lambda *a, **k: pages.popleft())  # type: ignore[method-assign]
    assert await api.get_invoices() == [{"n": 1}, {"n": 2}]


async def test_notifications_count(api: EtollApi) -> None:
    api._get = AsyncMock(return_value={"count": 3})  # type: ignore[method-assign]
    assert await api.get_notifications_count() == 3


# ------------------------------------------------------------ refresh token
TOKEN_EXPIRED = {**TOKEN_OK, "expires_in": 1}  # expiră imediat (marjă de 30 s)


async def test_expired_access_token_uses_refresh_token(
    api: EtollApi, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(
        TOKEN_URL,
        side_effect=_queue({"json": TOKEN_EXPIRED}, {"json": TOKEN_OK}),
    )
    aioclient_mock.get(URL_TOLLS, json={"tolls": []})

    await api.login()
    await api.get_tolls()

    posts = [c for c in aioclient_mock.mock_calls if c[0].lower() == "post"]
    assert len(posts) == 2
    assert posts[1][2]["grant_type"] == "refresh_token"


async def test_rejected_refresh_token_falls_back_to_login(
    api: EtollApi, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(
        TOKEN_URL,
        side_effect=_queue(
            {"json": TOKEN_EXPIRED},
            {"status": 400, "json": {"error": "invalid_grant"}},
            {"json": TOKEN_OK},
        ),
    )
    aioclient_mock.get(URL_TOLLS, json={"tolls": []})

    await api.login()
    await api.get_tolls()

    grants = [
        c[2]["grant_type"] for c in aioclient_mock.mock_calls if c[0].lower() == "post"
    ]
    assert grants == ["password", "refresh_token", "password"]


async def test_non_dict_pages_yield_empty_lists(api: EtollApi) -> None:
    api._get = AsyncMock(return_value=["unexpected"])  # type: ignore[method-assign]
    assert await api.get_tolls() == []
    assert await api.get_invoices() == []

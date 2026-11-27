"""Client async pentru API-ul portalului CNAIR eToll (etoll.ro)."""

from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

from .const import (
    CLIENT_ID,
    TOKEN_URL,
    URL_INVOICES,
    URL_NOTIFICATIONS,
    URL_TOLLS,
    URL_VEHICLES,
)

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=30)


class EtollError(Exception):
    """Eroare generică."""


class EtollAuthError(EtollError):
    """Autentificare eșuată."""


class EtollConnectionError(EtollError):
    """Eroare de conexiune."""


class EtollHttpError(EtollError):
    """Răspuns HTTP neașteptat (altul decât 200 și 401)."""

    def __init__(self, status: int, message: str = "") -> None:
        super().__init__(f"HTTP {status}: {message}" if message else f"HTTP {status}")
        self.status = status


class EtollRateLimitError(EtollHttpError):
    """HTTP 429; `retry_after` (secunde) vine din antetul Retry-After, dacă există."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__(429)
        self.retry_after = retry_after


def _parse_retry_after(value: str | None) -> float | None:
    """Retry-After în secunde; forma cu dată HTTP nu e suportată."""
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


class EtollApi:
    """Client API: password grant Keycloak + Bearer pe portal.etoll.ro/api."""

    def __init__(
        self, session: aiohttp.ClientSession, username: str, password: str
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0.0
        self._refresh_expires_at: float = 0.0

    # ------------------------------------------------------------------ auth
    async def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        try:
            async with self._session.post(
                TOKEN_URL, data=data, timeout=_TIMEOUT
            ) as resp:
                try:
                    body = await resp.json(content_type=None)
                except Exception:  # noqa: BLE001
                    body = {}
                if resp.status in (400, 401):
                    raise EtollAuthError(
                        f"{(body or {}).get('error', 'auth')}: "
                        f"{(body or {}).get('error_description', resp.status)}"
                    )
                if resp.status != 200 or not body or "access_token" not in body:
                    raise EtollError(f"Răspuns token neașteptat (HTTP {resp.status})")
                return body
        except (aiohttp.ClientError, TimeoutError) as err:
            raise EtollConnectionError(f"Eroare conexiune SSO: {err}") from err

    def _store(self, body: dict[str, Any]) -> None:
        now = time.monotonic()
        self._access_token = body["access_token"]
        self._refresh_token = body.get("refresh_token")
        self._expires_at = now + int(body.get("expires_in", 60)) - 30
        self._refresh_expires_at = now + int(body.get("refresh_expires_in", 0)) - 30

    async def login(self) -> None:
        """Autentificare cu user și parolă."""
        body = await self._token_request(
            {
                "grant_type": "password",
                "client_id": CLIENT_ID,
                "username": self._username,
                "password": self._password,
                "scope": "openid profile",
            }
        )
        self._store(body)
        _LOGGER.debug("Autentificare etoll reușită")

    async def _refresh(self) -> None:
        body = await self._token_request(
            {
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": self._refresh_token or "",
            }
        )
        self._store(body)

    async def _ensure_token(self) -> None:
        now = time.monotonic()
        if self._access_token and now < self._expires_at:
            return
        if self._refresh_token and now < self._refresh_expires_at:
            try:
                await self._refresh()
                return
            except EtollAuthError:
                _LOGGER.debug("Refresh token respins, relogin")
        await self.login()

    # --------------------------------------------------------------- cereri
    async def _get(
        self, url: str, params: dict[str, Any] | None = None, retry: bool = True
    ) -> Any:
        await self._ensure_token()
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }
        try:
            async with self._session.get(
                url, params=params, headers=headers, timeout=_TIMEOUT
            ) as resp:
                if resp.status == 401:
                    if retry:
                        self._access_token = None
                        self._expires_at = 0.0
                        return await self._get(url, params, retry=False)
                    raise EtollAuthError("HTTP 401")
                if resp.status == 429:
                    raise EtollRateLimitError(
                        _parse_retry_after(resp.headers.get("Retry-After"))
                    )
                if resp.status != 200:
                    text = await resp.text()
                    raise EtollHttpError(resp.status, text[:200])
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise EtollConnectionError(f"Eroare conexiune API: {err}") from err

    async def _get_cursor_paged(
        self, url: str, key: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Liste paginate pe cursor (`nextCursor`); se oprește la prima pagină goală."""
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(10):
            query = dict(params or {})
            if cursor:
                query["cursor"] = cursor
            page = await self._get(url, query)
            if not isinstance(page, dict):
                break
            batch = page.get(key) or []
            items.extend(batch)
            cursor = page.get("nextCursor")
            if not cursor or not batch:
                break
        return items

    async def get_tolls(self) -> list[dict[str, Any]]:
        return await self._get_cursor_paged(
            URL_TOLLS, "tolls", {"orderBy": "DSC", "size": 50}
        )

    async def get_vehicles(self) -> list[dict[str, Any]]:
        params = {"computeVignetteEligibility": "true", "size": 50}
        try:
            return await self._get_cursor_paged(URL_VEHICLES, "vehicles", params)
        except EtollHttpError as err:
            # Fallback doar pentru erori 4xx de cerere (ex. parametri respinși de
            # server); nu și pentru 403/429 (blocare/rate limit) sau erori de conexiune.
            if err.status in (403, 429) or not 400 <= err.status < 500:
                raise
            params["vehicleType"] = "CAR"
            return await self._get_cursor_paged(URL_VEHICLES, "vehicles", params)

    async def get_invoices(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for page_no in range(10):
            data = await self._get(URL_INVOICES, {"page": page_no, "size": 50})
            if not isinstance(data, dict):
                break
            items.extend(data.get("invoices") or [])
            page = data.get("page") or {}
            if page.get("last", True):
                break
        return items

    async def get_notifications_count(self) -> int | None:
        data = await self._get(URL_NOTIFICATIONS)
        return (data or {}).get("count")

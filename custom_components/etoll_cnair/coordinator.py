"""Coordinator: aduce și procesează datele contului eToll."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import EtollApi, EtollAuthError, EtollError, EtollRateLimitError
from .const import DOMAIN, INVALID_STATUSES

_LOGGER = logging.getLogger(__name__)


def parse_dt(value: Any) -> datetime | None:
    """ISO 8601 -> datetime cu fus orar (implicit fusul HA)."""
    if not value or not isinstance(value, str):
        return None
    dt = dt_util.parse_datetime(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return dt


def _is_vignette(toll: dict[str, Any]) -> bool:
    """Rovinieta se deosebește de pod/tichet rută prin vignetteIssueDate."""
    return (
        bool(toll.get("vignetteIssueDate"))
        or "VIGN" in str(toll.get("type", "")).upper()
    )


def _toll_kind(toll: dict[str, Any]) -> str:
    kind = str(toll.get("type", "")).upper()
    if _is_vignette(toll):
        return "vignette"
    if "BRIDGE" in kind:
        return "bridge"
    if "ROUTE" in kind or "TICKET" in kind:
        return "route"
    return "other"


def _price(toll: dict[str, Any]) -> float:
    value = (toll.get("price") or {}).get("totalPrice")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _day_diff(until: datetime, now: datetime) -> int:
    """Zile calendaristice până la data expirării (negativ după expirare)."""
    return (dt_util.as_local(until).date() - dt_util.as_local(now).date()).days


def _spending(tolls: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    year = dt_util.as_local(now).year
    by_year: dict[int, float] = {}
    kinds = {"vignette": 0.0, "bridge": 0.0, "route": 0.0, "other": 0.0}
    count = 0
    last: datetime | None = None
    for toll in tolls:
        if str(toll.get("status", "")).upper() in INVALID_STATUSES:
            continue
        when = parse_dt(toll.get("purchasedAt")) or parse_dt(toll.get("createdAt"))
        if when is None:
            continue
        y = dt_util.as_local(when).year
        by_year[y] = round(by_year.get(y, 0.0) + _price(toll), 2)
        if y == year:
            kinds[_toll_kind(toll)] += _price(toll)
            count += 1
            if last is None or when > last:
                last = when
    return {
        "total": round(by_year.get(year, 0.0), 2),
        "by_kind": {k: round(v, 2) for k, v in kinds.items()},
        "purchases": count,
        "last_purchase": last,
        "by_year": {str(y): v for y, v in sorted(by_year.items())},
    }


def _vignette_state(
    vehicle: dict[str, Any], toll: dict[str, Any] | None, now: datetime
) -> dict[str, Any]:
    """Expirarea vine din eligibilitatea vehiculului (acoperă și rovinietele
    cumpărate din alt canal); rezerva este rovinieta din contul curent."""
    elig = vehicle.get("vignetteEligibility") or {}
    until = parse_dt(elig.get("expirationDateCurrentVignette"))
    intervals = []
    for item in elig.get("activeVignetteIntervals") or []:
        s, e = parse_dt(item.get("start")), parse_dt(item.get("end"))
        if s and e:
            intervals.append((s, e))
    start = None
    if intervals:
        start = min(s for s, _ in intervals)
        until = until or max(e for _, e in intervals)
        active = any(s <= now < e for s, e in intervals)
    else:
        if toll:
            start = parse_dt(toll.get("validFrom"))
            until = until or parse_dt(toll.get("validUntil"))
        active = bool(until and until > now and (start is None or start <= now))
    return {
        "valid_from": start,
        "valid_until": until,
        "active": active,
        "days_left": _day_diff(until, now) if until else None,
    }


def build_data(
    tolls: list[dict[str, Any]],
    vehicles: list[dict[str, Any]],
    now: datetime,
) -> dict[str, dict[str, Any]]:
    """Grupează per număr de înmatriculare datele vehiculului și ale rovinietei."""
    result: dict[str, dict[str, Any]] = {}
    for veh in vehicles:
        plate = veh.get("plateNumber")
        if plate:
            result.setdefault(plate, {"vehicle": veh, "toll": None, "tolls": []})

    for toll in tolls:
        veh = toll.get("vehicle") or {}
        plate = veh.get("plateNumber")
        if not plate:
            continue
        entry = result.setdefault(plate, {"vehicle": veh, "toll": None, "tolls": []})
        entry["tolls"].append(toll)
        if (
            not _is_vignette(toll)
            or str(toll.get("status", "")).upper() in INVALID_STATUSES
        ):
            continue
        until = parse_dt(toll.get("validUntil"))
        best = entry["toll"]
        best_until = parse_dt(best.get("validUntil")) if best else None
        if until and (best_until is None or until > best_until):
            entry["toll"] = toll

    for entry in result.values():
        entry.update(_vignette_state(entry["vehicle"], entry["toll"], now))
        entry["spending"] = _spending(entry["tolls"], now)
    return result


def build_invoices(invoices: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    year = dt_util.as_local(now).year
    total = 0.0
    count = 0
    by_year: dict[int, float] = {}
    last: dict[str, Any] | None = None
    last_when: datetime | None = None
    for inv in invoices:
        when = parse_dt(inv.get("paymentDate"))
        amount = (inv.get("total") or {}).get("totalPrice")
        if when is None or not isinstance(amount, (int, float)):
            continue
        y = dt_util.as_local(when).year
        by_year[y] = round(by_year.get(y, 0.0) + float(amount), 2)
        if y == year:
            total += float(amount)
            count += 1
        if last_when is None or when > last_when:
            last_when, last = when, inv
    return {
        "year_total": round(total, 2),
        "year_count": count,
        "by_year": {str(y): v for y, v in sorted(by_year.items())},
        "last": last,
        "last_when": last_when,
    }


class EtollCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator eToll."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: EtollApi, minutes: int
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=minutes),
        )
        self.api = api
        # Ultimele valori reușite pentru datele secundare
        self._vehicles: list[dict[str, Any]] = []
        self._notifications: int | None = None
        self._invoices: list[dict[str, Any]] = []

    async def _optional(self, coro, last_known):
        """Date secundare: la erori non-auth se păstrează ultima valoare reușită."""
        try:
            return await coro
        except EtollAuthError:
            raise
        except EtollError as err:
            _LOGGER.debug("Date indisponibile, se păstrează ultima valoare: %s", err)
            return last_known

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            tolls = await self.api.get_tolls()
            self._vehicles = await self._optional(
                self.api.get_vehicles(), self._vehicles
            )
            self._notifications = await self._optional(
                self.api.get_notifications_count(), self._notifications
            )
            self._invoices = await self._optional(
                self.api.get_invoices(), self._invoices
            )
        except EtollAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EtollRateLimitError as err:
            _LOGGER.warning(
                "eToll a limitat cererile (HTTP 429), Retry-After: %s", err.retry_after
            )
            raise UpdateFailed(str(err)) from err
        except EtollError as err:
            raise UpdateFailed(str(err)) from err

        now = dt_util.utcnow()
        return {
            "vehicles": build_data(tolls, self._vehicles, now),
            "notifications": self._notifications,
            "invoices": build_invoices(self._invoices, now),
        }

"""Teste pentru coordinator: retenția ultimelor valori, erori, calcule."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.etoll_cnair.api import (
    EtollAuthError,
    EtollConnectionError,
    EtollHttpError,
    EtollRateLimitError,
)
from custom_components.etoll_cnair.coordinator import (
    build_data,
    build_invoices,
    parse_dt,
)

from .conftest import (
    EXPIRED_UNTIL,
    INVOICE,
    NOW,
    PLATE,
    VALID_UNTIL,
    make_toll,
    make_vehicle,
    setup_entry,
)


async def _loaded(
    hass: HomeAssistant, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
):
    freezer.move_to(NOW)
    await setup_entry(hass, entry)
    return entry.runtime_data


@pytest.mark.parametrize(
    "exc",
    [EtollHttpError(500), EtollRateLimitError(60), EtollConnectionError("down")],
)
async def test_secondary_data_kept_when_endpoints_fail(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    exc: Exception,
) -> None:
    """vehicles/invoices/notifications pică după un refresh reușit => se păstrează."""
    coordinator = await _loaded(hass, mock_config_entry, freezer)
    assert coordinator.data["invoices"]["year_total"] == 28.0
    assert coordinator.data["notifications"] == 2

    mock_api.get_vehicles.side_effect = exc
    mock_api.get_invoices.side_effect = exc
    mock_api.get_notifications_count.side_effect = exc
    await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert PLATE in coordinator.data["vehicles"]
    assert coordinator.data["vehicles"][PLATE]["vehicle"]["vin"]
    assert coordinator.data["invoices"]["year_total"] == 28.0
    assert coordinator.data["notifications"] == 2


async def test_secondary_data_updates_again_after_recovery(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    coordinator = await _loaded(hass, mock_config_entry, freezer)
    mock_api.get_notifications_count.side_effect = EtollHttpError(500)
    await coordinator.async_refresh()
    mock_api.get_notifications_count.side_effect = None
    mock_api.get_notifications_count.return_value = 7
    await coordinator.async_refresh()
    assert coordinator.data["notifications"] == 7


async def test_first_refresh_secondary_failure_is_empty_not_fatal(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Fără valoare anterioară, setup reușește cu date goale (nu cu eroare)."""
    mock_api.get_invoices.side_effect = EtollHttpError(500)
    mock_api.get_notifications_count.side_effect = EtollHttpError(500)
    coordinator = await _loaded(hass, mock_config_entry, freezer)
    assert coordinator.last_update_success is True
    assert coordinator.data["invoices"]["year_total"] == 0.0
    assert coordinator.data["notifications"] is None


async def test_429_on_tolls_is_update_failed_with_retry_after_logged(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    coordinator = await _loaded(hass, mock_config_entry, freezer)
    mock_api.get_tolls.side_effect = EtollRateLimitError(120.0)

    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    assert "Retry-After: 120.0" in caplog.text
    assert not list(mock_config_entry.async_get_active_flows(hass, {"reauth"}))


async def test_403_on_tolls_is_update_failed_without_reauth(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    coordinator = await _loaded(hass, mock_config_entry, freezer)
    mock_api.get_tolls.side_effect = EtollHttpError(403, "waf")

    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    assert not list(mock_config_entry.async_get_active_flows(hass, {"reauth"}))


async def test_401_on_tolls_starts_reauth(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    coordinator = await _loaded(hass, mock_config_entry, freezer)
    mock_api.get_tolls.side_effect = EtollAuthError("401")

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(list(mock_config_entry.async_get_active_flows(hass, {"reauth"}))) == 1


async def test_auth_error_on_secondary_endpoint_starts_reauth(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    coordinator = await _loaded(hass, mock_config_entry, freezer)
    mock_api.get_invoices.side_effect = EtollAuthError("401")

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(list(mock_config_entry.async_get_active_flows(hass, {"reauth"}))) == 1


# ------------------------------------------------------- funcții pure
def _now() -> datetime:
    return dt_util.parse_datetime(NOW)  # type: ignore[return-value]


def test_build_data_active_vignette() -> None:
    data = build_data([make_toll()], [make_vehicle()], _now())[PLATE]
    assert data["active"] is True
    assert data["days_left"] == 49
    assert data["spending"]["total"] == 28.0
    assert data["spending"]["by_kind"]["vignette"] == 28.0


def test_build_data_expired_gives_negative_days() -> None:
    data = build_data(
        [make_toll(until=EXPIRED_UNTIL)], [make_vehicle(until=EXPIRED_UNTIL)], _now()
    )[PLATE]
    assert data["active"] is False
    assert data["days_left"] == -7


def test_build_data_vehicle_without_vignette() -> None:
    vehicle = {"plateNumber": PLATE, "vin": "X"}
    data = build_data([], [vehicle], _now())[PLATE]
    assert data["active"] is False
    assert data["days_left"] is None
    assert data["valid_until"] is None


def test_build_data_falls_back_to_toll_when_no_eligibility() -> None:
    vehicle = {"plateNumber": PLATE}
    data = build_data([make_toll()], [vehicle], _now())[PLATE]
    assert data["active"] is True
    assert data["days_left"] == 49


def test_build_data_ignores_cancelled_vignette() -> None:
    toll = make_toll()
    toll["status"] = "CANCELLED"
    data = build_data([toll], [{"plateNumber": PLATE}], _now())[PLATE]
    assert data["active"] is False
    assert data["spending"]["total"] == 0.0


def test_build_data_toll_without_plate_is_skipped() -> None:
    toll = make_toll()
    toll["vehicle"] = {}
    assert build_data([toll], [], _now()) == {}


def test_build_invoices_totals_current_year_only() -> None:
    old = dict(INVOICE, paymentDate="2025-03-01T10:00:00+00:00")
    result = build_invoices([INVOICE, old], _now())
    assert result["year_total"] == 28.0
    assert result["year_count"] == 1
    assert result["by_year"] == {"2025": 28.0, "2026": 28.0}
    assert result["last"] is INVOICE


def test_build_invoices_ignores_malformed_entries() -> None:
    result = build_invoices(
        [{"paymentDate": None}, {"total": {"totalPrice": "x"}}], _now()
    )
    assert result["year_total"] == 0.0
    assert result["last"] is None


@pytest.mark.parametrize("value", [None, "", 123, "not-a-date"])
def test_parse_dt_invalid(value: object) -> None:
    assert parse_dt(value) is None


def test_parse_dt_naive_gets_default_timezone() -> None:
    parsed = parse_dt("2026-11-27T10:00:00")
    assert parsed is not None and parsed.tzinfo is not None


def test_spending_breakdown_by_toll_kind() -> None:
    def toll(kind: str, price: float) -> dict:
        return {
            "type": kind,
            "status": "ACTIVE",
            "purchasedAt": "2026-03-01T10:00:00+00:00",
            "price": {"totalPrice": price},
            "vehicle": {"plateNumber": PLATE},
        }

    tolls = [
        make_toll(),  # rovinietă, 28.0
        toll("BRIDGE_TOLL", 10.0),
        toll("ROUTE_TICKET", 5.5),
        toll("SOMETHING_ELSE", 1.0),
    ]
    spending = build_data(tolls, [make_vehicle()], _now())[PLATE]["spending"]

    assert spending["by_kind"] == {
        "vignette": 28.0,
        "bridge": 10.0,
        "route": 5.5,
        "other": 1.0,
    }
    assert spending["total"] == 44.5
    assert spending["purchases"] == 4


async def test_unavailability_logged_once_and_recovery_logged(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Regula `log-when-unavailable`: o singură eroare, apoi mesaj de revenire."""
    coordinator = await _loaded(hass, mock_config_entry, freezer)

    mock_api.get_tolls.side_effect = EtollConnectionError("down")
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    assert caplog.text.count("Error fetching") == 1

    mock_api.get_tolls.side_effect = None
    await coordinator.async_refresh()
    assert "recovered" in caplog.text


@pytest.mark.parametrize("reverse", [False, True])
def test_build_data_picks_vignette_with_latest_expiry(reverse: bool) -> None:
    """Fără eligibilitate pe vehicul, se alege rovinieta cu expirarea cea mai târzie."""
    early = make_toll(until="2026-12-31T21:59:59+00:00")
    late = make_toll(until=VALID_UNTIL)
    tolls = [late, early] if reverse else [early, late]

    data = build_data(tolls, [{"plateNumber": PLATE}], _now())[PLATE]

    assert data["toll"]["validUntil"] == VALID_UNTIL
    assert data["days_left"] == 49

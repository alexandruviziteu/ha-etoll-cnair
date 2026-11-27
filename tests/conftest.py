"""Fixturi comune; toate valorile sunt fictive."""

from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.etoll_cnair.api import EtollApi
from custom_components.etoll_cnair.const import DOMAIN

USERNAME = "user@example.com"
PASSWORD = "test-password"  # valoare fictivă
PLATE = "AB00XYZ"
VIN = "TESTVIN12345678901"

# "Acum" fixat în teste: 2026-11-27 12:00 UTC (04:00 în fusul implicit de test)
NOW = "2026-11-27 12:00:00+00:00"

VALID_UNTIL = "2027-01-15T21:59:59+00:00"  # 49 de zile după NOW (data locală)
EXPIRED_UNTIL = "2026-11-20T21:59:59+00:00"  # cu 7 zile înainte de NOW


def make_vehicle(
    plate: str = PLATE, vin: str = VIN, until: str = VALID_UNTIL
) -> dict[str, Any]:
    return {
        "plateNumber": plate,
        "vin": vin,
        "registrationSerial": "A123456",
        "category": "M1",
        "vehicleType": "CAR",
        "emissionStandard": "EURO_6",
        "isValid": True,
        "vignetteEligibility": {
            "expirationDateCurrentVignette": until,
            "activeVignetteIntervals": [
                {"start": "2026-01-16T00:00:00+00:00", "end": until}
            ],
        },
    }


def make_toll(plate: str = PLATE, until: str = VALID_UNTIL) -> dict[str, Any]:
    return {
        "type": "VIGNETTE",
        "status": "ACTIVE",
        "vignetteIssueDate": "2026-01-16T10:00:00+00:00",
        "validFrom": "2026-01-16T00:00:00+00:00",
        "validUntil": until,
        "purchasedAt": "2026-01-16T10:00:00+00:00",
        "price": {"totalPrice": 28.0},
        "duration": "ONE_YEAR",
        "vehicle": {"plateNumber": plate},
    }


INVOICE: dict[str, Any] = {
    "paymentDate": "2026-01-16T10:00:00+00:00",
    "total": {
        "totalPrice": 28.0,
        "priceWithoutVat": 23.53,
        "vat": 4.47,
        "vatPercentage": 19,
    },
    "externalSeries": "TST",
    "externalNumber": "1",
    "paymentMethod": "CARD",
    "types": ["VIGNETTE"],
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Permite încărcarea integrării din custom_components/."""


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="CNAIR eToll 2026",
        data={"username": USERNAME, "password": PASSWORD},
        unique_id=USERNAME,
    )


@pytest.fixture
def mock_api() -> Generator[SimpleNamespace]:
    """Înlocuiește metodele de rețea ale EtollApi; returnează mock-urile."""
    mocks = SimpleNamespace(
        login=AsyncMock(),
        get_tolls=AsyncMock(return_value=[make_toll()]),
        get_vehicles=AsyncMock(return_value=[make_vehicle()]),
        get_notifications_count=AsyncMock(return_value=2),
        get_invoices=AsyncMock(return_value=[INVOICE]),
    )
    with (
        patch.object(EtollApi, "login", mocks.login),
        patch.object(EtollApi, "get_tolls", mocks.get_tolls),
        patch.object(EtollApi, "get_vehicles", mocks.get_vehicles),
        patch.object(
            EtollApi, "get_notifications_count", mocks.get_notifications_count
        ),
        patch.object(EtollApi, "get_invoices", mocks.get_invoices),
    ):
        yield mocks


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

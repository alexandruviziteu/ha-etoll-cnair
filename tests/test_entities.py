"""Teste pentru entități: stări, clase de dispozitiv, înregistrare, dinamic."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.etoll_cnair.const import DOMAIN

from .conftest import (
    EXPIRED_UNTIL,
    INVOICE,
    NOW,
    PLATE,
    VIN,
    make_toll,
    make_vehicle,
    setup_entry,
)


def _entity_id(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    platform: str,
    key: str,
    plate: str | None = PLATE,
) -> str | None:
    suffix = f"{plate}_{key}" if plate else key
    return er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_{suffix}"
    )


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOW)
    await setup_entry(hass, entry)


async def test_expiry_sensor_is_a_date(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, mock_config_entry, freezer)
    entity_id = _entity_id(hass, mock_config_entry, "sensor", "vignette_expiry")
    assert entity_id
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "2027-01-15"  # dată ISO, nu text dd.mm.yyyy
    assert state.attributes["device_class"] == "date"


async def test_days_left_has_day_unit_and_duration_class(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, mock_config_entry, freezer)
    state = hass.states.get(
        _entity_id(hass, mock_config_entry, "sensor", "vignette_days_left")
    )
    assert state is not None
    assert state.state == "49"
    assert state.attributes["unit_of_measurement"] == "d"
    assert state.attributes["device_class"] == "duration"


async def test_days_left_negative_after_expiry(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_api.get_tolls.return_value = [make_toll(until=EXPIRED_UNTIL)]
    mock_api.get_vehicles.return_value = [make_vehicle(until=EXPIRED_UNTIL)]
    await _setup(hass, mock_config_entry, freezer)

    days = hass.states.get(
        _entity_id(hass, mock_config_entry, "sensor", "vignette_days_left")
    )
    active = hass.states.get(
        _entity_id(hass, mock_config_entry, "binary_sensor", "vignette_active")
    )
    assert days is not None and days.state == "-7"
    assert active is not None and active.state == "off"


async def test_vignette_active_binary_sensor_on(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, mock_config_entry, freezer)
    state = hass.states.get(
        _entity_id(hass, mock_config_entry, "binary_sensor", "vignette_active")
    )
    assert state is not None and state.state == "on"
    problem = hass.states.get(
        _entity_id(hass, mock_config_entry, "binary_sensor", "vehicle_data_problem")
    )
    assert problem is not None and problem.state == "off"


async def test_vin_and_certificate_are_diagnostic_and_disabled_by_default(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, mock_config_entry, freezer)
    registry = er.async_get(hass)
    for key in ("vin", "registration_certificate"):
        entity_id = _entity_id(hass, mock_config_entry, "sensor", key)
        assert entity_id, key
        entry = registry.async_get(entity_id)
        assert entry is not None
        assert entry.entity_category is EntityCategory.DIAGNOSTIC
        assert entry.disabled_by is RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(entity_id) is None  # dezactivat => fără stare


async def test_vin_not_exposed_in_any_attribute(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, mock_config_entry, freezer)
    for state in hass.states.async_all():
        assert VIN not in str(state.attributes), state.entity_id


async def test_expiry_sensor_attributes_are_clean(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, mock_config_entry, freezer)
    state = hass.states.get(
        _entity_id(hass, mock_config_entry, "sensor", "vignette_expiry")
    )
    assert state is not None
    assert state.attributes["plate_number"] == PLATE
    assert "vin" not in state.attributes


async def test_account_sensors(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, mock_config_entry, freezer)
    notifications = hass.states.get(
        _entity_id(hass, mock_config_entry, "sensor", "notifications", plate=None)
    )
    paid = hass.states.get(
        _entity_id(hass, mock_config_entry, "sensor", "year_paid", plate=None)
    )
    assert notifications is not None and notifications.state == "2"
    assert paid is not None and paid.state == "28.0"


async def test_new_vehicle_appears_dynamically(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, mock_config_entry, freezer)
    assert (
        _entity_id(hass, mock_config_entry, "sensor", "vignette_expiry", "CD11ABC")
        is None
    )

    mock_api.get_vehicles.return_value = [
        make_vehicle(),
        make_vehicle(plate="CD11ABC", vin="TESTVIN00000000002"),
    ]
    mock_api.get_tolls.return_value = [make_toll(), make_toll(plate="CD11ABC")]
    freezer.tick(timedelta(minutes=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    entity_id = _entity_id(
        hass, mock_config_entry, "sensor", "vignette_expiry", "CD11ABC"
    )
    assert entity_id
    state = hass.states.get(entity_id)
    assert state is not None and state.state == "2027-01-15"


async def test_vehicle_removed_from_account_becomes_unavailable(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, mock_config_entry, freezer)
    mock_api.get_vehicles.return_value = []
    mock_api.get_tolls.return_value = []
    freezer.tick(timedelta(minutes=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(
        _entity_id(hass, mock_config_entry, "sensor", "vignette_expiry")
    )
    assert state is not None and state.state == "unavailable"


async def test_last_invoice_billed_services_ignores_empty_types(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Regresie: `types` cu None/"" provoca TypeError la construirea atributelor."""
    mock_api.get_invoices.return_value = [{**INVOICE, "types": ["VIGNETTE", None, ""]}]
    await _setup(hass, mock_config_entry, freezer)

    state = hass.states.get(
        _entity_id(hass, mock_config_entry, "sensor", "last_invoice", plate=None)
    )
    assert state is not None
    assert state.state == "28.0"
    assert state.attributes["billed_services"] == "Vignette"


async def test_last_invoice_billed_services_absent_when_all_types_empty(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_api.get_invoices.return_value = [{**INVOICE, "types": [None, ""]}]
    await _setup(hass, mock_config_entry, freezer)

    state = hass.states.get(
        _entity_id(hass, mock_config_entry, "sensor", "last_invoice", plate=None)
    )
    assert state is not None
    assert "billed_services" not in state.attributes

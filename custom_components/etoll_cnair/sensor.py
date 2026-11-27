"""Senzori eToll: per vehicul și per cont."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import EtollConfigEntry
from .const import DOMAIN
from .coordinator import EtollCoordinator
from .entity import EtollVehicleEntity

PARALLEL_UPDATES = 0  # date centralizate în coordinator

CURRENCY = "RON"


def _clean(attrs: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in attrs.items() if v is not None}


def _iso(value: Any) -> str | None:
    return dt_util.as_local(value).isoformat() if value else None


def _local_date(value: Any) -> date | None:
    return dt_util.as_local(value).date() if value else None


def _vehicle(d: dict[str, Any]) -> dict[str, Any]:
    return d.get("vehicle") or {}


def _nice(value: Any) -> str | None:
    return str(value).replace("_", " ").title() if value else None


def _expiry_attrs(d: dict[str, Any]) -> dict[str, Any]:
    toll = d.get("toll") or {}
    veh = _vehicle(d)
    return _clean(
        {
            "plate_number": veh.get("plateNumber"),
            "expires_at": _iso(d.get("valid_until")),
            "days_remaining": d.get("days_left"),
            "valid_from": _iso(d.get("valid_from")),
            "validity_period": toll.get("duration"),
            "vignette_status": toll.get("status"),
            "price_paid": (toll.get("price") or {}).get("totalPrice"),
            "vignette_serial": (toll.get("issuance") or {}).get("serialNo"),
            "purchased_at": toll.get("purchasedAt"),
        }
    )


def _spending_attrs(d: dict[str, Any]) -> dict[str, Any]:
    s = d.get("spending") or {}
    kinds = s.get("by_kind") or {}
    return _clean(
        {
            "vignette_amount": kinds.get("vignette"),
            "bridge_amount": kinds.get("bridge"),
            "route_amount": kinds.get("route"),
            "other_amount": kinds.get("other") or None,
            "purchases_count": s.get("purchases"),
            "last_purchase": _iso(s.get("last_purchase")),
            "yearly_totals": s.get("by_year") or None,
        }
    )


@dataclass(frozen=True, kw_only=True)
class VehicleSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


VEHICLE_SENSORS: tuple[VehicleSensorDescription, ...] = (
    VehicleSensorDescription(
        key="vignette_expiry",
        icon="mdi:calendar-clock",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: _local_date(d.get("valid_until")),
        attrs_fn=_expiry_attrs,
    ),
    VehicleSensorDescription(
        key="vignette_expiry_timestamp",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.get("valid_until"),
    ),
    VehicleSensorDescription(
        key="vignette_days_left",
        icon="mdi:calendar-end",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
        value_fn=lambda d: d.get("days_left"),
    ),
    VehicleSensorDescription(
        key="plate_number",
        icon="mdi:car-info",
        value_fn=lambda d: _vehicle(d).get("plateNumber"),
        attrs_fn=lambda d: _clean(
            {
                "country_code": _vehicle(d).get("countryCode"),
                "temporary_plate": _vehicle(d).get("temporaryPlate"),
                "favorite": _vehicle(d).get("favorite"),
            }
        ),
    ),
    VehicleSensorDescription(
        key="vin",
        icon="mdi:identifier",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _vehicle(d).get("vin"),
    ),
    VehicleSensorDescription(
        key="registration_certificate",
        icon="mdi:card-account-details-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _vehicle(d).get("registrationSerial"),
    ),
    VehicleSensorDescription(
        key="vehicle_category",
        icon="mdi:car-side",
        value_fn=lambda d: _vehicle(d).get("category"),
        attrs_fn=lambda d: _clean(
            {
                "bridge_toll_category": _vehicle(d).get("strrPeajCategoryCode"),
                "vehicle_type": _vehicle(d).get("vehicleType"),
                "max_authorised_mass": _vehicle(d).get("mtma") or None,
            }
        ),
    ),
    VehicleSensorDescription(
        key="emission_standard",
        icon="mdi:molecule-co2",
        value_fn=lambda d: _nice(_vehicle(d).get("emissionStandard")),
    ),
    VehicleSensorDescription(
        key="spending_year",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY,
        value_fn=lambda d: (d.get("spending") or {}).get("total"),
        attrs_fn=_spending_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EtollConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    known: set[str] = set()

    def _add_new() -> None:
        new: list[Any] = []
        for plate in (coordinator.data or {}).get("vehicles", {}):
            if plate in known:
                continue
            known.add(plate)
            new += [VehicleSensor(coordinator, plate, desc) for desc in VEHICLE_SENSORS]
        if new:
            async_add_entities(new)

    async_add_entities(
        [
            NotificationsSensor(coordinator),
            LastInvoiceSensor(coordinator),
            YearPaidSensor(coordinator),
        ]
    )
    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class VehicleSensor(EtollVehicleEntity, SensorEntity):
    entity_description: VehicleSensorDescription

    def __init__(
        self,
        coordinator: EtollCoordinator,
        plate: str,
        description: VehicleSensorDescription,
    ) -> None:
        super().__init__(coordinator, plate, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        data = self._vehicle
        return self.entity_description.value_fn(data) if data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self._vehicle
        fn = self.entity_description.attrs_fn
        return fn(data) if data and fn else None


class _AccountSensor(CoordinatorEntity[EtollCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _key = ""

    def __init__(self, coordinator: EtollCoordinator) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_translation_key = self._key
        self._attr_unique_id = f"{entry_id}_{self._key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="CNAIR eToll 2026",
            manufacturer="CNAIR",
        )

    @property
    def _inv(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("invoices") or {}


class NotificationsSensor(_AccountSensor):
    _key = "notifications"

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("notifications")


class LastInvoiceSensor(_AccountSensor):
    _key = "last_invoice"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY

    @property
    def native_value(self):
        return ((self._inv.get("last") or {}).get("total") or {}).get("totalPrice")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        inv = self._inv.get("last")
        if not inv:
            return None
        total = inv.get("total") or {}
        number = f"{inv.get('externalSeries') or ''} {inv.get('externalNumber') or ''}".strip()
        return _clean(
            {
                "invoice_number": number or None,
                "payment_date": _iso(self._inv.get("last_when")),
                "payment_method": _nice(inv.get("paymentMethod")),
                "billed_services": ", ".join(
                    label for t in inv.get("types") or [] if (label := _nice(t))
                )
                or None,
                "amount_without_vat": total.get("priceWithoutVat"),
                "vat_amount": total.get("vat"),
                "vat_rate": total.get("vatPercentage"),
            }
        )


class YearPaidSensor(_AccountSensor):
    _key = "year_paid"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY

    @property
    def native_value(self):
        return self._inv.get("year_total")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self._inv:
            return None
        return _clean(
            {
                "invoices_count": self._inv.get("year_count"),
                "yearly_totals": self._inv.get("by_year") or None,
            }
        )

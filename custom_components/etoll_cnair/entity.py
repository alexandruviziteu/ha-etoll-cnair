"""Entitate de bază per vehicul."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EtollCoordinator


class EtollVehicleEntity(CoordinatorEntity[EtollCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: EtollCoordinator, plate: str, key: str) -> None:
        super().__init__(coordinator)
        self._plate = plate
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{plate}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{plate}")},
            name=f"Rovinietă {plate}",
            manufacturer="CNAIR",
            model="Rovinietă (eToll)",
        )

    @property
    def _vehicle(self) -> dict | None:
        return (self.coordinator.data or {}).get("vehicles", {}).get(self._plate)

    @property
    def available(self) -> bool:
        return super().available and self._vehicle is not None

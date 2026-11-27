"""Binary sensors: rovinieta activă și datele vehiculului."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EtollConfigEntry
from .coordinator import EtollCoordinator
from .entity import EtollVehicleEntity

PARALLEL_UPDATES = 0  # date centralizate în coordinator


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
            if plate not in known:
                known.add(plate)
                new += [
                    VignetteActiveSensor(coordinator, plate),
                    VehicleDataProblemSensor(coordinator, plate),
                ]
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class VignetteActiveSensor(EtollVehicleEntity, BinarySensorEntity):
    def __init__(self, coordinator: EtollCoordinator, plate: str) -> None:
        super().__init__(coordinator, plate, "vignette_active")

    @property
    def is_on(self) -> bool | None:
        return self._vehicle.get("active") if self._vehicle else None


class VehicleDataProblemSensor(EtollVehicleEntity, BinarySensorEntity):
    """Pornit când contul eToll marchează datele vehiculului ca invalide."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: EtollCoordinator, plate: str) -> None:
        super().__init__(coordinator, plate, "vehicle_data_problem")

    @property
    def is_on(self) -> bool | None:
        if not self._vehicle:
            return None
        valid = (self._vehicle.get("vehicle") or {}).get("isValid")
        return None if valid is None else not valid

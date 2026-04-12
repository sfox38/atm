"""Sensor platform for ATM per-token telemetry."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.dt import utcnow

from .const import DOMAIN
from .helpers import token_name_slug

if TYPE_CHECKING:
    from .data import ATMData
    from .token_store import TokenRecord

_SENSOR_TYPES = (
    "status",
    "request_count",
    "denied_count",
    "rate_limit_hits",
    "last_access",
    "expires_in",
)


def _make_sensors(
    token: TokenRecord,
    data: ATMData,
) -> list[ATMTokenSensor]:
    """Create the full set of sensor entities for one token."""
    slug = token_name_slug(token.name)
    return [ATMTokenSensor(token, slug, sensor_type, data) for sensor_type in _SENSOR_TYPES]


class ATMTokenSensor(SensorEntity):
    """HA sensor entity representing one telemetry dimension for an ATM token.

    One sensor is created per entry in _SENSOR_TYPES per active token. Sensors
    are removed immediately when a token is revoked or archived.
    """

    _attr_should_poll = False
    _attr_has_entity_name = False

    _NUMERIC_TYPES = frozenset({"request_count", "denied_count", "rate_limit_hits", "expires_in"})
    _COUNT_TYPES = frozenset({"request_count", "denied_count", "rate_limit_hits"})

    def __init__(
        self,
        token: TokenRecord,
        slug: str,
        sensor_type: str,
        data: ATMData,
    ) -> None:
        self._token = token
        self._slug = slug
        self._sensor_type = sensor_type
        self._data = data
        self._attr_unique_id = f"atm_{slug}_{sensor_type}"
        self._attr_name = f"ATM {token.name} {sensor_type.replace('_', ' ').title()}"

        if sensor_type in self._COUNT_TYPES:
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        elif sensor_type == "expires_in":
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement = "d"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._token.id)},
            name=f"ATM Token: {self._token.name}",
            manufacturer="ATM",
            model="Token",
        )

    @property
    def native_value(self):
        token = self._token
        sensor_type = self._sensor_type

        if sensor_type == "status":
            if token.revoked:
                return "revoked"
            if token.is_expired():
                return "expired"
            return "active"

        if sensor_type == "request_count":
            return self._data.token_counters.get(token.id, {}).get("request_count", 0)

        if sensor_type == "denied_count":
            return self._data.token_counters.get(token.id, {}).get("denied_count", 0)

        if sensor_type == "rate_limit_hits":
            return self._data.token_counters.get(token.id, {}).get("rate_limit_hits", 0)

        if sensor_type == "last_access":
            if token.last_used_at is None:
                return "never"
            return token.last_used_at.isoformat()

        if sensor_type == "expires_in":
            if token.expires_at is None:
                return -1
            delta = token.expires_at - utcnow()
            return max(0, math.ceil(delta.total_seconds() / 86400))

        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize the sensor platform and create sensors for all existing tokens."""
    data: ATMData = hass.data[DOMAIN]
    data.async_add_entities_cb = async_add_entities

    sensors: list[ATMTokenSensor] = []
    for token in data.store.list_tokens():
        slug = token_name_slug(token.name)
        token_sensors = _make_sensors(token, data)
        data.platform_entities[slug] = token_sensors
        sensors.extend(token_sensors)

    if sensors:
        async_add_entities(sensors)


async def async_create_token_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    token: TokenRecord,
) -> None:
    """Create and register sensor entities for a newly created token."""
    data: ATMData = hass.data[DOMAIN]
    if data.async_add_entities_cb is None:
        return
    slug = token_name_slug(token.name)
    token_sensors = _make_sensors(token, data)
    data.platform_entities[slug] = token_sensors
    data.async_add_entities_cb(token_sensors)


async def async_remove_token_sensors(
    hass: HomeAssistant,
    token_slug: str,
) -> None:
    """Remove sensor entities for a revoked/archived token and clean up the entity registry.

    Removing from the entity registry prevents 'unavailable' ghost entries after
    the token is gone.
    """
    from homeassistant.helpers import entity_registry as er
    data: ATMData = hass.data[DOMAIN]
    sensors = data.platform_entities.pop(token_slug, [])
    registry = er.async_get(hass)
    for sensor in sensors:
        await sensor.async_remove()
        if sensor.unique_id:
            entry = registry.async_get_entity_id(
                "sensor", DOMAIN, sensor.unique_id
            )
            if entry:
                registry.async_remove(entry)

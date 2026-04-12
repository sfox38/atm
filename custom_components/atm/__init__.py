"""Advanced Token Management (ATM) custom integration for Home Assistant."""

from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, Event
from homeassistant.helpers import area_registry as ar_mod
from homeassistant.helpers import device_registry as dr_mod
from homeassistant.helpers import entity_registry as er_mod
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from .audit import AuditLog
from .const import AUDIT_STORAGE_KEY, AUDIT_STORAGE_VERSION, DOMAIN, EXPIRY_CHECK_INTERVAL, FLUSH_INTERVAL
from .data import ATMData
from .helpers import archive_expired_token, cancel_expiry_timer, schedule_expiry_timer, terminate_token_connections
from .rate_limiter import RateLimiter
from .token_store import TokenStore

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ATM from a config entry.

    Initialises storage, registers admin views and the panel unconditionally.
    Proxy and MCP views are only registered when the kill switch is off.
    Schedules a periodic flush of last_used_at timestamps and wires registry
    change listeners to invalidate the entity tree cache.
    """
    store = await TokenStore.async_create(hass)
    rate_limiter = RateLimiter()
    audit_store = Store(hass, AUDIT_STORAGE_VERSION, AUDIT_STORAGE_KEY)
    audit = AuditLog(store=audit_store, maxlen=store.get_settings().audit_log_maxlen)
    await audit.async_load()

    data = ATMData(
        store=store,
        rate_limiter=rate_limiter,
        audit=audit,
        sse_connections={},
    )
    hass.data[DOMAIN] = data

    from .admin_view import ALL_ADMIN_VIEWS
    for view_cls in ALL_ADMIN_VIEWS:
        view = view_cls()
        view.hass = hass
        hass.http.register_view(view)

    from .panel import async_register_atm_panel
    await async_register_atm_panel(hass)

    settings = store.get_settings()

    async def _register_routes() -> None:
        """Register the proxy and MCP views. Skipped when kill switch is active."""
        from .proxy_view import ALL_VIEWS
        from .mcp_view import ALL_MCP_VIEWS
        for view_cls in ALL_VIEWS + ALL_MCP_VIEWS:
            view = view_cls()
            view.hass = hass
            hass.http.register_view(view)

    if not settings.kill_switch:
        await _register_routes()

    from .sensor import async_create_token_sensors, async_remove_token_sensors

    async def _on_token_created(token) -> None:
        """Create sensor entities when a new token is minted."""
        await async_create_token_sensors(hass, entry, token)
        schedule_expiry_timer(hass, data, token)

    async def _on_token_archived(token_slug: str) -> None:
        """Remove sensor entities when a token is revoked or archived."""
        await async_remove_token_sensors(hass, token_slug)

    data.async_on_token_created = _on_token_created
    data.async_on_token_archived = _on_token_archived

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _flush_last_used(_now=None) -> None:
        await store.async_flush_last_used()

    cancel_flush = async_track_time_interval(hass, _flush_last_used, FLUSH_INTERVAL)
    entry.async_on_unload(cancel_flush)

    async def _audit_flush_loop() -> None:
        while True:
            interval = data.store.get_settings().audit_flush_interval
            if interval == 0:
                await asyncio.sleep(300)
                continue
            await asyncio.sleep(interval * 60)
            await audit.async_save()

    audit_task = hass.async_create_background_task(
        _audit_flush_loop(), "atm_audit_flush_loop"
    )
    entry.async_on_unload(audit_task.cancel)

    async def _check_expired_tokens(_now=None) -> None:
        for token in list(store.list_tokens()):
            if token.is_expired():
                await archive_expired_token(hass, data, token)

    await _check_expired_tokens()
    for _token in store.list_tokens():
        schedule_expiry_timer(hass, data, _token)
    cancel_expiry = async_track_time_interval(hass, _check_expired_tokens, EXPIRY_CHECK_INTERVAL)
    entry.async_on_unload(cancel_expiry)
    entry.async_on_unload(lambda: [cancel_expiry_timer(data, tid) for tid in list(data.expiry_timers)])

    async def _on_stop(event: Event) -> None:
        audit_task.cancel()
        await store.async_flush_last_used()
        await audit.async_save()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop)
    )

    def _invalidate_entity_tree(_event=None) -> None:
        data.entity_tree_cache_valid = False

    for _registry_event in (
        er_mod.EVENT_ENTITY_REGISTRY_UPDATED,
        dr_mod.EVENT_DEVICE_REGISTRY_UPDATED,
        ar_mod.EVENT_AREA_REGISTRY_UPDATED,
    ):
        entry.async_on_unload(
            hass.bus.async_listen(_registry_event, _invalidate_entity_tree)
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Tear down ATM: terminate SSE connections, unload sensor platform, remove panel."""
    data: ATMData = hass.data.get(DOMAIN)
    if data is not None:
        for token_id in list(data.sse_connections.keys()):
            await terminate_token_connections(token_id, data.sse_connections)
        await data.audit.async_save()

    from .panel import remove_atm_panel
    remove_atm_panel(hass)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data.pop(DOMAIN, None)

    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config entry migration handler. Currently a no-op (single storage version)."""
    return True

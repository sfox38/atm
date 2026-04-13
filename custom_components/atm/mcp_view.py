"""MCP SSE endpoint for the ATM integration."""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import logging
import uuid
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util.dt import utcnow

from .audit import generate_request_id
from .const import (
    ATM_VERSION,
    BLOCKED_DOMAINS,
    DOMAIN,
    DUAL_GATE_SERVICES,
    HIGH_RISK_DOMAINS,
    MAX_SSE_CONNECTIONS_PER_TOKEN,
    PROXY_TIMEOUT_SECONDS,
    SSE_HEARTBEAT_INTERVAL,
    TOKEN_LENGTH,
    TOKEN_PREFIX,
)
from .data import ATMData
from .helpers import (
    FilteredStates as _FilteredStates,
    ScrubbedState as _ScrubbedState,
    archive_expired_token,
    build_error_response as _error,
    fire_rate_limit_events as _fire_rate_limit_events,
    get_authenticated_token as _get_authenticated_token,
    get_client_ip as _get_client_ip,
    log_request as _log,
    parse_time_param as _parse_time_param,
    read_json_body as _read_json_body,
)
from .policy_engine import (
    EntityCreationNotPermitted,
    Permission,
    filter_entities_for_token,
    filter_service_response,
    resolve,
    resolve_service_targets,
    scrub_sensitive_attributes,
    scrub_state_dict as _scrub_state_dict,
)
from .rate_limiter import RateLimitResult
from .token_store import TokenRecord

_LOGGER = logging.getLogger(__name__)

_MCP_VERSION = "2024-11-05"

_ENTITY_TOOL_DEFS: list[dict] = [
    {
        "name": "get_state",
        "description": "Get the current state of a Home Assistant entity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "description": "Entity ID, e.g. light.living_room."},
            },
            "required": ["entity_id"],
        },
    },
    {
        "name": "get_states",
        "description": "Get the current state of all accessible Home Assistant entities.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_history",
        "description": "Get the state history for a Home Assistant entity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "start_time": {
                    "type": "string",
                    "description": "ISO timestamp or relative string (24h, 7d, 2w, 1m).",
                },
                "end_time": {
                    "type": "string",
                    "description": "ISO timestamp or relative string. Defaults to now.",
                },
            },
            "required": ["entity_id", "start_time"],
        },
    },
    {
        "name": "get_statistics",
        "description": "Get long-term statistics for a Home Assistant entity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "start_time": {"type": "string"},
                "end_time": {"type": "string"},
                "period": {
                    "type": "string",
                    "enum": ["5minute", "hour", "day", "week", "month"],
                    "default": "hour",
                },
                "statistic_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Subset of: mean, min, max, sum, state, change.",
                },
            },
            "required": ["entity_id", "start_time"],
        },
    },
    {
        "name": "call_service",
        "description": "Call a Home Assistant service.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Service domain, e.g. light."},
                "service": {"type": "string", "description": "Service name, e.g. turn_on."},
                "service_data": {"type": "object", "description": "Additional service parameters."},
                "entity_id": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                    "description": "Target entity ID or list of entity IDs.",
                },
                "device_id": {"type": "string"},
                "area_id": {"type": "string"},
            },
            "required": ["domain", "service"],
        },
    },
]

_SYSTEM_TOOL_DEFS: list[dict] = [
    {
        "name": "get_config",
        "description": "Get the Home Assistant configuration.",
        "flag": "allow_config_read",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "render_template",
        "description": "Render a Jinja2 template in Home Assistant.",
        "flag": "allow_template_render",
        "inputSchema": {
            "type": "object",
            "properties": {
                "template": {"type": "string", "description": "Jinja2 template string."},
            },
            "required": ["template"],
        },
    },
    {
        "name": "create_automation",
        "description": "Create a new Home Assistant automation.",
        "flag": "allow_automation_write",
        "inputSchema": {
            "type": "object",
            "properties": {
                "config": {"type": "object", "description": "Automation configuration."},
            },
            "required": ["config"],
        },
    },
    {
        "name": "edit_automation",
        "description": "Edit an existing Home Assistant automation.",
        "flag": "allow_automation_write",
        "inputSchema": {
            "type": "object",
            "properties": {
                "automation_id": {"type": "string"},
                "config": {"type": "object"},
            },
            "required": ["automation_id", "config"],
        },
    },
    {
        "name": "delete_automation",
        "description": "Delete a Home Assistant automation.",
        "flag": "allow_automation_write",
        "inputSchema": {
            "type": "object",
            "properties": {
                "automation_id": {"type": "string"},
            },
            "required": ["automation_id"],
        },
    },
    {
        "name": "restart_ha",
        "description": "Restart Home Assistant.",
        "flag": "allow_restart",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _jsonrpc_result(msg_id: Any, result: Any) -> dict:
    """Wrap a result in a JSON-RPC 2.0 success envelope."""
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _jsonrpc_error(msg_id: Any, code: int, message: str) -> dict:
    """Wrap an error in a JSON-RPC 2.0 error envelope."""
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _tool_success(text: str) -> dict:
    """Return an MCP tool result content block with a plain-text payload."""
    return {"content": [{"type": "text", "text": text}]}


def _tool_error(message: str) -> dict:
    """Return an MCP tool result content block indicating an error."""
    return {"content": [{"type": "text", "text": message}], "isError": True}


async def _tool_get_state(
    args: dict, token: TokenRecord, hass: Any
) -> tuple[dict, str, str]:
    """MCP tool: return the current state of a single entity."""
    entity_id = args.get("entity_id", "")
    if not entity_id:
        return _tool_error("Missing required argument: entity_id"), "denied", "get_state"

    perm = resolve(entity_id, token, hass)
    if perm == Permission.NOT_FOUND:
        return _tool_error("Entity not found."), "not_found", entity_id
    if perm in (Permission.NO_ACCESS, Permission.DENY):
        return _tool_error("Entity not found."), "denied", entity_id

    state = hass.states.get(entity_id)
    if state is None:
        return _tool_error("Entity not found."), "not_found", entity_id

    return _tool_success(json.dumps(scrub_sensitive_attributes(state), default=str)), "allowed", entity_id


async def _tool_get_states(
    args: dict, token: TokenRecord, hass: Any
) -> tuple[dict, str, str]:
    """MCP tool: return all entities accessible to the token."""
    states = hass.states.async_all()
    filtered = filter_entities_for_token(states, token, hass)
    return _tool_success(json.dumps(filtered, default=str)), "allowed", "get_states"


async def _tool_get_history(
    args: dict, token: TokenRecord, hass: Any
) -> tuple[dict, str, str]:
    """MCP tool: fetch state history for a single permitted entity."""
    entity_id = args.get("entity_id", "")
    if not entity_id:
        return _tool_error("Missing required argument: entity_id"), "denied", "get_history"

    perm = resolve(entity_id, token, hass)
    if perm == Permission.NOT_FOUND:
        return _tool_error("Entity not found."), "not_found", entity_id
    if perm in (Permission.NO_ACCESS, Permission.DENY):
        return _tool_error("Entity not found."), "denied", entity_id

    start_time_raw = args.get("start_time", "")
    if not start_time_raw:
        return _tool_error("Missing required argument: start_time"), "denied", entity_id

    try:
        start_time = _parse_time_param(start_time_raw)
    except ValueError:
        return _tool_error("Invalid start_time format."), "denied", entity_id

    end_time = None
    end_time_raw = args.get("end_time")
    if end_time_raw:
        try:
            end_time = _parse_time_param(end_time_raw)
        except ValueError:
            return _tool_error("Invalid end_time format."), "denied", entity_id

    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder import history as rec_history

        fn = functools.partial(
            rec_history.get_significant_states,
            hass,
            start_time,
            end_time,
            [entity_id],
            None,
            False,
            True,
            False,
            False,
        )
        result = await get_instance(hass).async_add_executor_job(fn)
    except Exception:
        _LOGGER.warning("MCP history call failed for entity %s", entity_id, exc_info=True)
        return _tool_error("History call failed."), "denied", entity_id

    output = {}
    for eid, states_list in result.items():
        output[eid] = [
            _scrub_state_dict(s.as_dict() if hasattr(s, "as_dict") else s)
            for s in states_list
        ]

    return _tool_success(json.dumps(output, default=str)), "allowed", entity_id


async def _tool_get_statistics(
    args: dict, token: TokenRecord, hass: Any
) -> tuple[dict, str, str]:
    """MCP tool: fetch long-term statistics for a single permitted entity."""
    entity_id = args.get("entity_id", "")
    if not entity_id:
        return _tool_error("Missing required argument: entity_id"), "denied", "get_statistics"

    perm = resolve(entity_id, token, hass)
    if perm == Permission.NOT_FOUND:
        return _tool_error("Entity not found."), "not_found", entity_id
    if perm in (Permission.NO_ACCESS, Permission.DENY):
        return _tool_error("Entity not found."), "denied", entity_id

    start_time_raw = args.get("start_time", "")
    if not start_time_raw:
        return _tool_error("Missing required argument: start_time"), "denied", entity_id

    try:
        start_time = _parse_time_param(start_time_raw)
    except ValueError:
        return _tool_error("Invalid start_time format."), "denied", entity_id

    end_time = None
    end_time_raw = args.get("end_time")
    if end_time_raw:
        try:
            end_time = _parse_time_param(end_time_raw)
        except ValueError:
            return _tool_error("Invalid end_time format."), "denied", entity_id

    period = args.get("period", "hour")
    if period not in ("5minute", "hour", "day", "week", "month"):
        return _tool_error("Invalid period. Must be one of: 5minute, hour, day, week, month."), "denied", entity_id

    valid_types = {"mean", "min", "max", "sum", "state", "change"}
    raw_types = args.get("statistic_types")
    type_set: set | None = None
    if raw_types:
        type_set = {t for t in raw_types if t in valid_types} or None

    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder import statistics as recorder_stats

        fn = functools.partial(
            recorder_stats.statistics_during_period,
            hass,
            start_time,
            end_time,
            {entity_id},
            period,
            None,
            # types became non-optional in HA 2026.4; default to all types when not specified.
            type_set or {"mean", "min", "max", "sum", "state", "change"},
        )
        result = await get_instance(hass).async_add_executor_job(fn)
    except Exception:
        _LOGGER.warning("MCP statistics call failed for entity %s", entity_id, exc_info=True)
        return _tool_error("Statistics call failed."), "denied", entity_id

    return _tool_success(json.dumps(result, default=str)), "allowed", entity_id


async def _tool_call_service(
    args: dict, token: TokenRecord, hass: Any, data: ATMData
) -> tuple[dict, str, str]:
    """MCP tool: call a HA service with entity targets filtered to WRITE-permitted entities."""
    domain = args.get("domain", "")
    service = args.get("service", "")
    if not domain or not service:
        return _tool_error("Missing required arguments: domain and service"), "denied", "call_service"

    resource = f"service:{domain}/{service}"
    service_key = f"{domain}/{service}"

    if service_key in DUAL_GATE_SERVICES and not token.allow_restart:
        return _tool_error("Forbidden."), "denied", resource

    entity_id = args.get("entity_id")
    device_id = args.get("device_id")
    area_id = args.get("area_id")
    service_data = args.get("service_data") or {}

    try:
        permitted_entities = resolve_service_targets(
            entity_id=entity_id,
            device_id=device_id,
            area_id=area_id,
            service_domain=domain,
            token=token,
            hass=hass,
        )
    except EntityCreationNotPermitted:
        return _tool_error("Forbidden."), "denied", resource

    if not permitted_entities:
        return _tool_error("Forbidden."), "denied", resource

    if domain in HIGH_RISK_DOMAINS:
        _LOGGER.info(
            "High-risk service call %s/%s by token %s",
            domain, service, token.name,
        )

    call_data = dict(service_data)
    call_data["entity_id"] = permitted_entities

    try:
        async with asyncio.timeout(PROXY_TIMEOUT_SECONDS):
            svc_response = await hass.services.async_call(
                domain,
                service,
                call_data,
                blocking=True,
                return_response=False,
            )
    except asyncio.TimeoutError:
        return (
            _tool_success(json.dumps({
                "success": True,
                "partial": True,
                "message": "Service dispatched but HA did not respond within the timeout window.",
            })),
            "allowed",
            resource,
        )
    except (ServiceNotFound, HomeAssistantError):
        return _tool_error("Forbidden."), "denied", resource

    filtered_response = filter_service_response(svc_response, token, hass) if svc_response is not None else None

    body: dict[str, Any] = {"success": True}
    if filtered_response is not None:
        body["service_response"] = filtered_response

    return _tool_success(json.dumps(body, default=str)), "allowed", resource


async def _tool_get_config(
    args: dict, token: TokenRecord, hass: Any
) -> tuple[dict, str, str]:
    """MCP tool: return HA config (requires allow_config_read or pass_through)."""
    if not token.allow_config_read and not token.pass_through:
        return _tool_error("Forbidden."), "denied", "get_config"
    config_dict = hass.config.as_dict()
    config_dict["components"] = [
        c for c in config_dict.get("components", [])
        if c != DOMAIN and not c.startswith(DOMAIN + ".")
    ]
    return _tool_success(json.dumps(config_dict, default=str)), "allowed", "get_config"



async def _tool_render_template(
    args: dict, token: TokenRecord, hass: Any
) -> tuple[dict, str, str]:
    """MCP tool: render a Jinja2 template against permitted entity state."""
    if not token.allow_template_render and not token.pass_through:
        return _tool_error("Forbidden."), "denied", "render_template"

    template_str = args.get("template", "")
    if not template_str:
        return _tool_error("Missing required argument: template"), "denied", "render_template"

    try:
        from homeassistant.helpers import template as template_helper

        if token.pass_through:
            permitted = {
                s.entity_id: _ScrubbedState(s)
                for s in hass.states.async_all()
                if s.entity_id.split(".")[0] not in BLOCKED_DOMAINS
            }
        else:
            permitted = {
                s.entity_id: _ScrubbedState(s)
                for s in hass.states.async_all()
                if resolve(s.entity_id, token, hass) in (Permission.READ, Permission.WRITE)
            }

        filtered_states = _FilteredStates(permitted)

        # Override all HA template state helpers with permission-restricted versions.
        def _state_attr(entity_id: str, attr: str):
            s = permitted.get(entity_id)
            return s.attributes.get(attr) if s is not None else None

        def _is_state(entity_id: str, value: str) -> bool:
            s = permitted.get(entity_id)
            return s is not None and s.state == value

        def _is_state_attr(entity_id: str, attr: str, value) -> bool:
            s = permitted.get(entity_id)
            return s is not None and s.attributes.get(attr) == value

        def _has_value(entity_id: str) -> bool:
            s = permitted.get(entity_id)
            return s is not None and s.state not in ("unknown", "unavailable")

        tmpl = template_helper.Template(template_str, hass)
        rendered = tmpl.async_render(variables={
            "states": filtered_states,
            "state_attr": _state_attr,
            "is_state": _is_state,
            "is_state_attr": _is_state_attr,
            "has_value": _has_value,
            # Block entity-enumeration HA globals that bypass ATM permission filtering.
            # Jinja2 local variables shadow globals of the same name.
            "integration_entities": lambda *a, **kw: [],
            "area_entities": lambda *a, **kw: [],
            "area_devices": lambda *a, **kw: [],
            "device_entities": lambda *a, **kw: [],
            "expand": lambda *a, **kw: [],
            "label_entities": lambda *a, **kw: [],
            "label_areas": lambda *a, **kw: [],
            "floor_entities": lambda *a, **kw: [],
            "floor_areas": lambda *a, **kw: [],
            # Block topology-enumeration globals that reveal unpermitted instance structure.
            "device_attr": lambda *a, **kw: None,
            "device_id": lambda *a, **kw: None,
            "areas": lambda *a, **kw: [],
            "labels": lambda *a, **kw: [],
            "label_id": lambda *a, **kw: None,
            "label_name": lambda *a, **kw: None,
            "floors": lambda *a, **kw: [],
            "floor_id": lambda *a, **kw: None,
            "floor_name": lambda *a, **kw: None,
            "closest": lambda *a, **kw: None,
            "is_device_attr": lambda *a, **kw: False,
            "area_id": lambda *a, **kw: None,
        })
    except Exception:
        return _tool_error("Template rendering failed. Check your template syntax."), "denied", "render_template"

    return _tool_success(str(rendered)), "allowed", "render_template"


async def _tool_automation_stub(
    tool_name: str, args: dict, token: TokenRecord
) -> tuple[dict, str, str]:
    """Placeholder for automation tools not yet implemented in v1."""
    if not token.allow_automation_write and not token.pass_through:
        return _tool_error("Forbidden."), "denied", tool_name
    return (
        _tool_error(
            "Automation tools are not yet implemented in ATM v1. "
            "Use ha-mcp or the HA native MCP endpoint for automation management."
        ),
        "allowed",
        tool_name,
    )


async def _tool_restart_ha(
    args: dict, token: TokenRecord, hass: Any
) -> tuple[dict, str, str]:
    """MCP tool: restart HA (requires allow_restart flag on the token)."""
    if not token.allow_restart:
        return _tool_error("Forbidden. The allow_restart flag must be enabled on this token."), "denied", "restart_ha"

    try:
        async with asyncio.timeout(PROXY_TIMEOUT_SECONDS):
            await hass.services.async_call(
                "homeassistant",
                "restart",
                {},
                blocking=True,
            )
    except asyncio.TimeoutError:
        return (
            _tool_success(json.dumps({"success": True, "partial": True, "message": "Restart dispatched."})),
            "allowed",
            "restart_ha",
        )
    except (ServiceNotFound, HomeAssistantError):
        return _tool_error("Restart failed."), "denied", "restart_ha"

    return _tool_success(json.dumps({"success": True})), "allowed", "restart_ha"


async def _call_tool(
    tool_name: str,
    arguments: dict,
    token: TokenRecord,
    hass: Any,
    data: ATMData,
) -> tuple[dict, str, str]:
    """Route a tools/call request to the appropriate tool handler."""
    if tool_name == "get_state":
        return await _tool_get_state(arguments, token, hass)
    if tool_name == "get_states":
        return await _tool_get_states(arguments, token, hass)
    if tool_name == "get_history":
        return await _tool_get_history(arguments, token, hass)
    if tool_name == "get_statistics":
        return await _tool_get_statistics(arguments, token, hass)
    if tool_name == "call_service":
        return await _tool_call_service(arguments, token, hass, data)
    if tool_name == "get_config":
        return await _tool_get_config(arguments, token, hass)
    if tool_name == "render_template":
        return await _tool_render_template(arguments, token, hass)
    if tool_name in ("create_automation", "edit_automation", "delete_automation"):
        return await _tool_automation_stub(tool_name, arguments, token)
    if tool_name == "restart_ha":
        return await _tool_restart_ha(arguments, token, hass)
    return _tool_error(f"Unknown tool: {tool_name}"), "denied", tool_name


def _resolve_area_id(entry: Any, device_registry: Any) -> str | None:
    """Return the area_id for an entity registry entry, falling back to the device's area."""
    if entry is None:
        return None
    if entry.area_id:
        return entry.area_id
    if entry.device_id:
        device = device_registry.async_get(entry.device_id)
        if device and device.area_id:
            return device.area_id
    return None


def _build_server_info(token: TokenRecord, hass: Any) -> dict:
    """Build the atm://server-info resource payload for the MCP resources/read endpoint."""
    states = hass.states.async_all()
    if token.pass_through:
        count = sum(1 for s in states if s.entity_id.split(".")[0] not in BLOCKED_DOMAINS)
    else:
        filtered = filter_entities_for_token(states, token, hass)
        count = len(filtered)

    base_url = ""
    try:
        base_url = str(hass.config.internal_url or hass.config.external_url or "")
    except Exception:
        pass

    return {
        "name": "ATM Scoped Proxy",
        "version": ATM_VERSION,
        "token_name": token.name,
        "permitted_entity_count": count,
        "capability_flags": {
            "allow_config_read": token.allow_config_read,
            "allow_automation_write": token.allow_automation_write,
            "allow_template_render": token.allow_template_render,
            "allow_restart": token.allow_restart,
        },
        "native_ha_mcp_endpoint": f"{base_url}/api/mcp",
        "atm_context_endpoint": f"{base_url}/api/atm/mcp/context",
    }


def _get_effective_hint(token: TokenRecord, entity_id: str, hass: Any) -> str | None:
    """Return the most specific hint for an entity, checking entity then device then domain nodes."""
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    permissions = token.permissions

    entity_node = permissions.entities.get(entity_id)
    if entity_node and entity_node.hint:
        return entity_node.hint

    if entry and entry.device_id:
        device_node = permissions.devices.get(entry.device_id)
        if device_node and device_node.hint:
            return device_node.hint

    domain = entity_id.split(".")[0]
    domain_node = permissions.domains.get(domain)
    if domain_node and domain_node.hint:
        return domain_node.hint

    return None


def _build_context_plain(token: TokenRecord, hass: Any) -> str:
    """Build the plain-text context document listing accessible entities and capabilities."""
    lines: list[str] = []

    if token.pass_through:
        states = hass.states.async_all()
        count = sum(1 for s in states if s.entity_id.split(".")[0] not in BLOCKED_DOMAINS)
        lines.append("This token operates in pass-through mode.")
        lines.append(
            f"It has unrestricted access to all {count} accessible Home Assistant entities and services."
        )
        lines.append("")
        lines.append("The atm domain is always blocked regardless of token type.")
    else:
        states = hass.states.async_all()
        accessible: list[tuple[str, str, str | None]] = []
        for state in states:
            perm = resolve(state.entity_id, token, hass)
            if perm == Permission.WRITE:
                accessible.append((state.entity_id, "READ/WRITE", _get_effective_hint(token, state.entity_id, hass)))
            elif perm == Permission.READ:
                accessible.append((state.entity_id, "READ", _get_effective_hint(token, state.entity_id, hass)))

        accessible.sort(key=lambda x: x[0])
        lines.append("You have access to the following Home Assistant entities:")
        if accessible:
            for eid, perm_str, hint in accessible:
                hint_part = f' - "{hint}"' if hint else ""
                lines.append(f"- {eid} ({perm_str}){hint_part}")
        else:
            lines.append("(none)")
        lines.append("")
        lines.append(
            "You cannot access any other entities. "
            "Do not attempt to call services on entities not listed above."
        )

    lines.append("")
    lines.append("Capability flags enabled for this token:")
    lines.append(f"- Config read: {'yes' if (token.allow_config_read or token.pass_through) else 'no'}")
    lines.append(f"- Automation write: {'yes' if (token.allow_automation_write or token.pass_through) else 'no'}")
    lines.append(f"- Template render: {'yes' if (token.allow_template_render or token.pass_through) else 'no'}")
    lines.append(f"- Restart: {'yes' if token.allow_restart else 'no'}")
    lines.append("")
    if token.rate_limit_requests > 0:
        lines.append(
            f"Rate limit: {token.rate_limit_requests} requests/min, burst {token.rate_limit_burst}/sec"
        )
    else:
        lines.append("Rate limit: none")

    return "\n".join(lines)


def _build_context_json(token: TokenRecord, hass: Any) -> dict:
    """Build the structured JSON context document for the ?format=json context endpoint."""
    registry = er.async_get(hass)
    dev_registry = dr.async_get(hass)

    entities: list[dict] = []
    states = hass.states.async_all()

    if token.pass_through:
        for state in states:
            if state.entity_id.split(".")[0] in BLOCKED_DOMAINS:
                continue
            entry = registry.async_get(state.entity_id)
            area_id = _resolve_area_id(entry, dev_registry)
            entities.append({
                "entity_id": state.entity_id,
                "permission": "READ/WRITE",
                "area_id": area_id,
            })
    else:
        for state in states:
            perm = resolve(state.entity_id, token, hass)
            if perm not in (Permission.READ, Permission.WRITE):
                continue
            entry = registry.async_get(state.entity_id)
            area_id = _resolve_area_id(entry, dev_registry)
            perm_str = "READ/WRITE" if perm == Permission.WRITE else "READ"
            e: dict = {"entity_id": state.entity_id, "permission": perm_str, "area_id": area_id}
            hint = _get_effective_hint(token, state.entity_id, hass)
            if hint:
                e["hint"] = hint
            entities.append(e)

    entities.sort(key=lambda e: e["entity_id"])

    return {
        "token_name": token.name,
        "pass_through": token.pass_through,
        "entities": entities,
        "capability_flags": {
            "allow_config_read": token.allow_config_read,
            "allow_automation_write": token.allow_automation_write,
            "allow_template_render": token.allow_template_render,
            "allow_restart": token.allow_restart,
        },
        "rate_limit": {
            "requests_per_minute": token.rate_limit_requests,
            "burst_per_second": token.rate_limit_burst,
        },
    }


async def _dispatch_mcp(
    method: str,
    msg_id: Any,
    params: dict,
    token: TokenRecord,
    hass: Any,
    data: ATMData,
    client_ip: str,
) -> tuple[dict | None, str, str, str]:
    """Dispatch one MCP method call.

    Returns (response_msg, log_method, log_resource, outcome).
    response_msg is None for notifications that require no response.
    """
    request_id = generate_request_id()

    if method == "initialize":
        resp = _jsonrpc_result(msg_id, {
            "protocolVersion": _MCP_VERSION,
            "capabilities": {
                "tools": {},
                "resources": {"subscribe": False},
            },
            "serverInfo": {"name": "ATM", "version": ATM_VERSION},
        })
        _log(data, token, request_id=request_id, method="initialize",
             resource="/api/atm/mcp", outcome="allowed", client_ip=client_ip)
        return resp, "initialize", "/api/atm/mcp", "allowed"

    if method in ("notifications/initialized", "initialized"):
        _log(data, token, request_id=request_id, method=method,
             resource="/api/atm/mcp", outcome="allowed", client_ip=client_ip)
        return None, method, "/api/atm/mcp", "allowed"

    if method == "ping":
        resp = _jsonrpc_result(msg_id, {})
        _log(data, token, request_id=request_id, method="ping",
             resource="/api/atm/mcp", outcome="allowed", client_ip=client_ip)
        return resp, "ping", "/api/atm/mcp", "allowed"

    if method == "tools/list":
        tools = list(_ENTITY_TOOL_DEFS)
        for tool_def in _SYSTEM_TOOL_DEFS:
            flag = tool_def["flag"]
            flag_enabled = token.pass_through or getattr(token, flag, False)
            if flag_enabled:
                tools.append({k: v for k, v in tool_def.items() if k != "flag"})
        resp = _jsonrpc_result(msg_id, {"tools": tools})
        _log(data, token, request_id=request_id, method="tools/list",
             resource="/api/atm/mcp", outcome="allowed", client_ip=client_ip)
        return resp, "tools/list", "/api/atm/mcp", "allowed"

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments") or {}
        tool_result, outcome, resource = await _call_tool(tool_name, arguments, token, hass, data)
        _log(data, token, request_id=request_id, method=tool_name or "tools/call",
             resource=resource, outcome=outcome, client_ip=client_ip)
        return _jsonrpc_result(msg_id, tool_result), tool_name or "tools/call", resource, outcome

    if method == "resources/list":
        resp = _jsonrpc_result(msg_id, {
            "resources": [{
                "uri": "atm://server-info",
                "name": "ATM Server Info",
                "mimeType": "application/json",
            }]
        })
        _log(data, token, request_id=request_id, method="resources/list",
             resource="/api/atm/mcp", outcome="allowed", client_ip=client_ip)
        return resp, "resources/list", "/api/atm/mcp", "allowed"

    if method == "resources/read":
        uri = params.get("uri", "")
        if uri != "atm://server-info":
            if msg_id is not None:
                _log(data, token, request_id=request_id, method="resources/read",
                     resource=uri or "/api/atm/mcp", outcome="denied", client_ip=client_ip)
                return _jsonrpc_error(msg_id, -32602, "Unknown resource URI."), "resources/read", uri, "denied"
            return None, "resources/read", uri, "denied"
        server_info = _build_server_info(token, hass)
        resp = _jsonrpc_result(msg_id, {
            "contents": [{
                "uri": "atm://server-info",
                "mimeType": "application/json",
                "text": json.dumps(server_info, default=str),
            }]
        })
        _log(data, token, request_id=request_id, method="resources/read",
             resource="atm://server-info", outcome="allowed", client_ip=client_ip)
        return resp, "resources/read", "atm://server-info", "allowed"

    if msg_id is not None:
        _log(data, token, request_id=request_id, method=method or "unknown",
             resource="/api/atm/mcp", outcome="denied", client_ip=client_ip)
        return _jsonrpc_error(msg_id, -32601, "Method not found."), method or "unknown", "/api/atm/mcp", "denied"

    return None, method or "unknown", "/api/atm/mcp", "denied"


class ATMMcpSseView(HomeAssistantView):
    """GET /api/atm/mcp - SSE endpoint (MCP 2024-11-05 transport).
    POST /api/atm/mcp - Streamable HTTP transport (MCP 2025-03-26).
    """

    url = "/api/atm/mcp"
    name = "api:atm:mcp:sse"
    requires_auth = False

    async def get(self, request: web.Request) -> web.StreamResponse | web.Response:
        """Open an SSE stream. Sends an 'endpoint' event with the messages URL, then heartbeats."""
        hass = self.hass
        data: ATMData = hass.data[DOMAIN]
        request_id = generate_request_id()
        client_ip = _get_client_ip(request)

        if data.store.get_settings().kill_switch:
            return _error("service_unavailable", "Service unavailable.", 503, request_id)

        _401 = _error("unauthorized", "Unauthorized.", 401, request_id)
        _401.headers["WWW-Authenticate"] = 'Bearer realm="ATM"'

        for key in ("token", "access_token"):

            if key in request.query:
                return _401

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return _401

        presented = auth_header[7:]
        if not presented.startswith(TOKEN_PREFIX) or len(presented) != TOKEN_LENGTH:
            return _401

        token_hash = hashlib.sha256(presented.encode()).hexdigest()
        token = data.store.get_token_by_hash(token_hash)
        if token is None:
            return _401

        if token.revoked:
            return _401

        if token.is_expired():
            await archive_expired_token(hass, data, token)
            return _401

        # SSE connection limit check after validity checks so revoked tokens cannot
        # probe connection counts via 429 vs 401 differential timing.
        current_count = len(data.sse_connections.get(token.id, set()))
        if current_count >= MAX_SSE_CONNECTIONS_PER_TOKEN:
            _log(data, token, request_id=request_id, method="GET", resource="/api/atm/mcp",
                 outcome="rate_limited", client_ip=client_ip)
            return _error("rate_limited", "Too many SSE connections for this token.", 429, request_id)

        rl_result = data.rate_limiter.check(token.id, token.rate_limit_requests, token.rate_limit_burst)
        if not rl_result.allowed:
            _fire_rate_limit_events(hass, data, token)
            _log(data, token, request_id=request_id, method="GET", resource="/api/atm/mcp",
                 outcome="rate_limited", client_ip=client_ip)
            resp = _error("rate_limited", "Rate limit exceeded.", 429, request_id)
            resp.headers["Retry-After"] = str(rl_result.retry_after)
            return resp

        data.store.update_last_used(token.id, utcnow())
        _log(data, token, request_id=request_id, method="GET", resource="/api/atm/mcp",
             outcome="allowed", client_ip=client_ip)

        session_id = str(uuid.uuid4())
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)

        data.mcp_sessions[session_id] = (queue, token.id)
        if token.id not in data.sse_connections:
            data.sse_connections[token.id] = set()
        data.sse_connections[token.id].add(queue)

        def _cleanup() -> None:
            data.mcp_sessions.pop(session_id, None)
            conns = data.sse_connections.get(token.id)
            if conns is not None:
                conns.discard(queue)
                if not conns:
                    data.sse_connections.pop(token.id, None)

        # Re-check token after queue insertion to close the TOCTOU window where
        # a DELETE/archive could have run between auth check and queue add.
        # Must happen BEFORE response.prepare() - once headers are sent the
        # connection is bound to SSE and returning a web.Response is invalid.
        if data.store.get_token_by_id(token.id) is None:
            _cleanup()
            return _error("unauthorized", "Unauthorized.", 401, request_id)

        response = web.StreamResponse()
        response.headers["Content-Type"] = "text/event-stream"
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        response.headers["X-ATM-Request-ID"] = request_id

        try:
            await response.prepare(request)

            base_url = str(request.url.origin())
            messages_url = f"{base_url}/api/atm/mcp/messages?session_id={session_id}"
            await response.write(f"event: endpoint\ndata: {messages_url}\n\n".encode())

            session_epoch = data.wipe_epoch
            try:
                while True:
                    try:
                        msg = await asyncio.wait_for(
                            queue.get(),
                            timeout=SSE_HEARTBEAT_INTERVAL.total_seconds(),
                        )
                    except asyncio.TimeoutError:
                        if data.wipe_epoch != session_epoch:
                            break
                        await response.write(b": heartbeat\n\n")
                        continue
                    if msg is None:
                        break
                    await response.write(
                        f"event: message\ndata: {json.dumps(msg, default=str)}\n\n".encode()
                    )
            except ConnectionResetError:
                pass
        finally:
            _cleanup()

        return response

    async def post(self, request: web.Request) -> web.Response:
        """Handle Streamable HTTP transport (MCP 2025-03-26)."""
        hass = self.hass
        data: ATMData = hass.data[DOMAIN]
        request_id = generate_request_id()
        client_ip = _get_client_ip(request)

        result = await _get_authenticated_token(
            hass, request, data, request_id, "/api/atm/mcp"
        )
        if isinstance(result, web.Response):
            return result
        token, rl_result = result

        body_result = await _read_json_body(request, request_id)
        if isinstance(body_result, web.Response):
            return body_result
        body = body_result

        if body.get("jsonrpc") != "2.0":
            return web.Response(
                status=400,
                content_type="application/json",
                text=json.dumps(_jsonrpc_error(body.get("id"), -32600, "Invalid Request.")),
                headers={"X-ATM-Request-ID": request_id},
            )

        msg_id = body.get("id")
        method = body.get("method", "")
        params = body.get("params") or {}

        response_msg, _log_method, _log_resource, _outcome = await _dispatch_mcp(
            method, msg_id, params, token, hass, data, client_ip
        )

        if response_msg is None:
            return web.Response(status=202, headers={"X-ATM-Request-ID": request_id})

        resp = web.Response(
            status=200,
            content_type="application/json",
            text=json.dumps(response_msg, default=str),
            headers={"X-ATM-Request-ID": request_id},
        )
        if token.rate_limit_requests > 0:
            resp.headers["X-RateLimit-Limit"] = str(token.rate_limit_requests)
            resp.headers["X-RateLimit-Remaining"] = str(rl_result.remaining)
            resp.headers["X-RateLimit-Reset"] = str(rl_result.reset)
        return resp


class ATMMcpMessagesView(HomeAssistantView):
    """POST /api/atm/mcp/messages - receive a JSON-RPC message and push the response to the SSE queue."""

    url = "/api/atm/mcp/messages"
    name = "api:atm:mcp:messages"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        hass = self.hass
        data: ATMData = hass.data[DOMAIN]
        request_id = generate_request_id()
        client_ip = _get_client_ip(request)

        result = await _get_authenticated_token(
            hass, request, data, request_id, "/api/atm/mcp/messages"
        )
        if isinstance(result, web.Response):
            return result
        token, _rl = result

        body_result = await _read_json_body(request, request_id)
        if isinstance(body_result, web.Response):
            return body_result
        body = body_result

        session_id = request.query.get("session_id", "")
        session_entry = data.mcp_sessions.get(session_id)
        if session_entry is None:
            return _error("invalid_request", "Invalid or expired session.", 400, request_id)

        queue, owner_token_id = session_entry
        if owner_token_id != token.id:
            return _error("unauthorized", "Unauthorized.", 401, request_id)

        if body.get("jsonrpc") != "2.0":
            if body.get("id") is not None:
                try:
                    queue.put_nowait(_jsonrpc_error(body.get("id"), -32600, "Invalid Request."))
                except asyncio.QueueFull:
                    return _error("service_unavailable", "SSE queue full; client is not reading.", 503, request_id)
            return web.Response(
                status=202,
                headers={"X-ATM-Request-ID": request_id},
            )

        msg_id = body.get("id")
        method = body.get("method", "")
        params = body.get("params") or {}

        response_msg, _log_method, _log_resource, _outcome = await _dispatch_mcp(
            method, msg_id, params, token, hass, data, client_ip
        )

        if response_msg is not None:
            try:
                queue.put_nowait(response_msg)
            except asyncio.QueueFull:
                return _error("service_unavailable", "SSE queue full; client is not reading.", 503, request_id)

        return web.Response(
            status=202,
            headers={"X-ATM-Request-ID": request_id},
        )


class ATMMcpContextView(HomeAssistantView):
    """GET /api/atm/mcp/context - context document listing accessible entities and capability flags.

    Returns plain text by default; pass ?format=json for a structured JSON response.
    """

    url = "/api/atm/mcp/context"
    name = "api:atm:mcp:context"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass = self.hass
        data: ATMData = hass.data[DOMAIN]
        request_id = generate_request_id()
        client_ip = _get_client_ip(request)

        result = await _get_authenticated_token(
            hass, request, data, request_id, "/api/atm/mcp/context"
        )
        if isinstance(result, web.Response):
            return result
        token, _rl = result

        _log(data, token, request_id=request_id, method="GET", resource="/api/atm/mcp/context",
             outcome="allowed", client_ip=client_ip)

        fmt = request.query.get("format", "")
        if fmt == "json":
            body = _build_context_json(token, hass)
            return web.Response(
                status=200,
                content_type="application/json",
                text=json.dumps(body, default=str),
                headers={"X-ATM-Request-ID": request_id},
            )

        text = _build_context_plain(token, hass)
        return web.Response(
            status=200,
            content_type="text/plain",
            text=text,
            headers={"X-ATM-Request-ID": request_id},
        )


ALL_MCP_VIEWS: list[type[HomeAssistantView]] = [
    ATMMcpSseView,
    ATMMcpMessagesView,
    ATMMcpContextView,
]

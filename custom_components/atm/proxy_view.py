"""REST proxy views for the ATM integration."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound

from .audit import generate_request_id
from .const import (
    BLOCKED_DOMAINS,
    DOMAIN,
    DUAL_GATE_SERVICES,
    PROXY_TIMEOUT_SECONDS,
)
from .data import ATMData
from .helpers import (
    FilteredStates as _FilteredStates,
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
    expand_service_targets,
    filter_entities_for_token,
    filter_service_response,
    resolve,
    resolve_service_targets,
    scrub_sensitive_attributes,
    scrub_state_dict as _scrub_state_dict,
)
from .rate_limiter import RateLimitResult
from .token_store import TokenRecord


def _json_response(
    body: Any,
    status: int,
    request_id: str,
    rl_result: RateLimitResult | None = None,
    extra_headers: dict[str, str] | None = None,
) -> web.Response:
    """Return a JSON success response. Adds X-RateLimit-* headers when rate limiting is active."""
    headers: dict[str, str] = {"X-ATM-Request-ID": request_id}
    if rl_result is not None and rl_result.rate_limiting_enabled:
        headers["X-RateLimit-Limit"] = str(rl_result.limit)
        headers["X-RateLimit-Remaining"] = str(rl_result.remaining)
        headers["X-RateLimit-Reset"] = str(rl_result.reset)
    if extra_headers:
        headers.update(extra_headers)
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps(body, default=str),
        headers=headers,
    )


def _count_service_targets(
    entity_id: Any,
    device_id: Any,
    area_id: Any,
    service_domain: str,
    hass: Any,
) -> int:
    """Count raw target entities before permission filtering.

    Used to populate X-ATM-Entities-Requested so the caller can see how many
    entities were silently filtered out by ATM permissions.
    """
    candidates, explicit_ids = expand_service_targets(
        entity_id=entity_id,
        device_id=device_id,
        area_id=area_id,
        service_domain=service_domain,
        hass=hass,
    )
    return len(candidates | set(explicit_ids))



class ATMRootView(HomeAssistantView):
    """GET /api/atm/ - health check endpoint."""

    url = "/api/atm/"
    name = "api:atm:root"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass = self.hass
        data: ATMData = hass.data[DOMAIN]
        request_id = generate_request_id()

        result = await _get_authenticated_token(hass, request, data, request_id, "/api/atm/")
        if isinstance(result, web.Response):
            return result
        token, rl_result = result

        _log(data, token, request_id=request_id, method="GET", resource="/api/atm/",
             outcome="allowed", client_ip=_get_client_ip(request))
        return _json_response({"message": "API running."}, 200, request_id, rl_result)


class ATMStatesView(HomeAssistantView):
    """GET /api/atm/states - list all entities accessible to the token."""

    url = "/api/atm/states"
    name = "api:atm:states"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass = self.hass
        data: ATMData = hass.data[DOMAIN]
        request_id = generate_request_id()

        result = await _get_authenticated_token(hass, request, data, request_id, "/api/atm/states")
        if isinstance(result, web.Response):
            return result
        token, rl_result = result

        try:
            limit = min(int(request.query.get("limit", 500)), 500)
            offset = max(int(request.query.get("offset", 0)), 0)
        except ValueError:
            return _error("invalid_request", "Invalid pagination parameters.", 400, request_id)

        states = hass.states.async_all()
        filtered = filter_entities_for_token(states, token, hass)
        page = filtered[offset:offset + limit]

        _log(data, token, request_id=request_id, method="GET", resource="/api/atm/states",
             outcome="allowed", client_ip=_get_client_ip(request))
        return _json_response(page, 200, request_id, rl_result)


class ATMStateView(HomeAssistantView):
    """GET /api/atm/states/{entity_id} - get state for a single entity."""

    url = "/api/atm/states/{entity_id}"
    name = "api:atm:state"
    requires_auth = False

    async def get(self, request: web.Request, entity_id: str) -> web.Response:
        hass = self.hass
        data: ATMData = hass.data[DOMAIN]
        request_id = generate_request_id()
        resource = f"/api/atm/states/{entity_id}"
        client_ip = _get_client_ip(request)

        result = await _get_authenticated_token(hass, request, data, request_id, resource)
        if isinstance(result, web.Response):
            return result
        token, rl_result = result

        perm = resolve(entity_id, token, hass)

        if perm == Permission.NOT_FOUND:
            _log(data, token, request_id=request_id, method="GET", resource=resource,
                 outcome="not_found", client_ip=client_ip)
            return _error("not_found", "Entity not found.", 404, request_id)

        if perm in (Permission.NO_ACCESS, Permission.DENY):
            _log(data, token, request_id=request_id, method="GET", resource=resource,
                 outcome="denied", client_ip=client_ip)
            # Return identical 404 body to avoid revealing entity existence.
            return _error("not_found", "Entity not found.", 404, request_id)

        state = hass.states.get(entity_id)
        if state is None:
            _log(data, token, request_id=request_id, method="GET", resource=resource,
                 outcome="not_found", client_ip=client_ip)
            return _error("not_found", "Entity not found.", 404, request_id)

        _log(data, token, request_id=request_id, method="GET", resource=entity_id,
             outcome="allowed", client_ip=client_ip)
        return _json_response(scrub_sensitive_attributes(state), 200, request_id, rl_result)


class ATMServiceView(HomeAssistantView):
    """POST /api/atm/services/{domain}/{service} - call a HA service."""

    url = "/api/atm/services/{domain}/{service}"
    name = "api:atm:service"
    requires_auth = False

    async def post(self, request: web.Request, domain: str, service: str) -> web.Response:
        hass = self.hass
        data: ATMData = hass.data[DOMAIN]
        request_id = generate_request_id()
        resource = f"service:{domain}/{service}"
        client_ip = _get_client_ip(request)

        result = await _get_authenticated_token(hass, request, data, request_id, resource)
        if isinstance(result, web.Response):
            return result
        token, rl_result = result

        body = await _read_json_body(request, request_id)
        if isinstance(body, web.Response):
            return body

        service_key = f"{domain}/{service}"
        if service_key in DUAL_GATE_SERVICES and not token.allow_restart:
            _log(data, token, request_id=request_id, method="POST", resource=resource,
                 outcome="denied", client_ip=client_ip)
            return _error("forbidden", "Forbidden.", 403, request_id)

        entity_id = body.get("entity_id")
        device_id = body.get("device_id")
        area_id = body.get("area_id")
        service_data = {k: v for k, v in body.items() if k not in ("entity_id", "device_id", "area_id")}

        requested_count = _count_service_targets(entity_id, device_id, area_id, domain, hass)

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
            _log(data, token, request_id=request_id, method="POST", resource=resource,
                 outcome="denied", client_ip=client_ip)
            return _error("forbidden", "Forbidden.", 403, request_id)

        if not permitted_entities:
            _log(data, token, request_id=request_id, method="POST", resource=resource,
                 outcome="denied", client_ip=client_ip)
            return _error("forbidden", "Forbidden.", 403, request_id)

        affected_count = len(permitted_entities)
        call_data = dict(service_data)
        call_data["entity_id"] = permitted_entities

        extra = {
            "X-ATM-Entities-Requested": str(requested_count),
            "X-ATM-Entities-Affected": str(affected_count),
        }

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
            _log(data, token, request_id=request_id, method="POST", resource=resource,
                 outcome="allowed", client_ip=client_ip)
            return _json_response(
                {"success": True, "partial": True, "message": "Service dispatched but HA did not respond within the timeout window."},
                200, request_id, rl_result, extra_headers=extra,
            )
        except (ServiceNotFound, HomeAssistantError):
            _log(data, token, request_id=request_id, method="POST", resource=resource,
                 outcome="denied", client_ip=client_ip)
            return _error("forbidden", "Forbidden.", 403, request_id)

        filtered_response = filter_service_response(svc_response, token, hass) if svc_response is not None else None

        _log(data, token, request_id=request_id, method="POST", resource=resource,
             outcome="allowed", client_ip=client_ip)

        resp_body: dict[str, Any] = {"success": True}
        if filtered_response is not None:
            resp_body["service_response"] = filtered_response

        return _json_response(resp_body, 200, request_id, rl_result, extra_headers=extra)


class ATMHistoryView(HomeAssistantView):
    """GET /api/atm/history/period/{timestamp} - state history for permitted entities."""

    url = "/api/atm/history/period/{timestamp}"
    name = "api:atm:history"
    requires_auth = False

    async def get(self, request: web.Request, timestamp: str) -> web.Response:
        hass = self.hass
        data: ATMData = hass.data[DOMAIN]
        request_id = generate_request_id()
        resource = "/api/atm/history"
        client_ip = _get_client_ip(request)

        result = await _get_authenticated_token(hass, request, data, request_id, resource)
        if isinstance(result, web.Response):
            return result
        token, rl_result = result

        start_time_raw = request.query.get("start_time", timestamp)
        try:
            start_time = _parse_time_param(start_time_raw)
        except ValueError:
            return _error("invalid_request", "Invalid start_time.", 400, request_id)

        end_time = None
        end_time_raw = request.query.get("end_time")
        if end_time_raw:
            try:
                end_time = _parse_time_param(end_time_raw)
            except ValueError:
                return _error("invalid_request", "Invalid end_time.", 400, request_id)

        all_states = hass.states.async_all()
        filtered_states = filter_entities_for_token(all_states, token, hass)
        permitted_set: set[str] = {s["entity_id"] for s in filtered_states}

        filter_entity_id = request.query.get("filter_entity_id")
        if filter_entity_id:
            requested_ids = [e.strip() for e in filter_entity_id.split(",")]
            permitted_ids = [e for e in requested_ids if e in permitted_set]
        else:
            permitted_ids = list(permitted_set)

        if not permitted_ids:
            _log(data, token, request_id=request_id, method="GET", resource=resource,
                 outcome="allowed", client_ip=client_ip)
            return _json_response({}, 200, request_id, rl_result)

        try:
            import functools

            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder import history as rec_history

            fn = functools.partial(
                rec_history.get_significant_states,
                hass,
                start_time,
                end_time,
                permitted_ids,
                None,   # filters
                False,  # include_start_time_state
                request.query.get("significant_changes_only", "1") != "0",
                "minimal_response" in request.query,
                "no_attributes" in request.query,
            )
            history_result = await get_instance(hass).async_add_executor_job(fn)
        except Exception:
            return _error("gateway_timeout", "History call failed.", 504, request_id)

        limit_int: int | None = None
        limit_raw = request.query.get("limit")
        if limit_raw:
            try:
                limit_int = int(limit_raw)
            except ValueError:
                pass

        output: dict[str, Any] = {}
        for eid, states in history_result.items():
            state_dicts = [
                _scrub_state_dict(s.as_dict() if hasattr(s, "as_dict") else s)
                for s in states
            ]
            if limit_int is not None and len(state_dicts) > limit_int:
                output[eid] = {"states": state_dicts[:limit_int], "truncated": True}
            else:
                output[eid] = state_dicts

        _log(data, token, request_id=request_id, method="GET", resource=resource,
             outcome="allowed", client_ip=client_ip)
        return _json_response(output, 200, request_id, rl_result)


class ATMStatisticsView(HomeAssistantView):
    """GET /api/atm/statistics - long-term statistics for permitted entities."""

    url = "/api/atm/statistics"
    name = "api:atm:statistics"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass = self.hass
        data: ATMData = hass.data[DOMAIN]
        request_id = generate_request_id()
        resource = "/api/atm/statistics"
        client_ip = _get_client_ip(request)

        result = await _get_authenticated_token(hass, request, data, request_id, resource)
        if isinstance(result, web.Response):
            return result
        token, rl_result = result

        start_time_raw = request.query.get("start_time")
        if not start_time_raw:
            return _error("invalid_request", "start_time is required.", 400, request_id)
        try:
            start_time = _parse_time_param(start_time_raw)
        except ValueError:
            return _error("invalid_request", "Invalid start_time.", 400, request_id)

        end_time = None
        end_time_raw = request.query.get("end_time")
        if end_time_raw:
            try:
                end_time = _parse_time_param(end_time_raw)
            except ValueError:
                return _error("invalid_request", "Invalid end_time.", 400, request_id)

        period = request.query.get("period", "hour")
        if period not in ("5minute", "hour", "day", "week", "month"):
            return _error("invalid_request", "Invalid period.", 400, request_id)

        valid_types = {"mean", "min", "max", "sum", "state", "change"}
        raw_types = request.query.get("statistic_types", "")
        if raw_types:
            type_set: set[str] | None = {t.strip() for t in raw_types.split(",") if t.strip() in valid_types}
            if not type_set:
                return _error("invalid_request", "No valid statistic_types provided.", 400, request_id)
        else:
            type_set = None

        all_states = hass.states.async_all()
        filtered_states = filter_entities_for_token(all_states, token, hass)
        permitted_set: set[str] = {s["entity_id"] for s in filtered_states}

        entity_ids_raw = request.query.get("entity_ids", "")
        if entity_ids_raw:
            requested_ids = {e.strip() for e in entity_ids_raw.split(",") if e.strip()}
            statistic_ids: set[str] = requested_ids & permitted_set
        else:
            statistic_ids = permitted_set

        if not statistic_ids:
            _log(data, token, request_id=request_id, method="GET", resource=resource,
                 outcome="allowed", client_ip=client_ip)
            return _json_response({}, 200, request_id, rl_result)

        try:
            import functools

            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder import statistics as recorder_stats

            fn = functools.partial(
                recorder_stats.statistics_during_period,
                hass,
                start_time,
                end_time,
                statistic_ids,
                period,
                None,
                # types became non-optional in HA 2026.4; default to all types when not specified.
                type_set or {"mean", "min", "max", "sum", "state", "change"},
            )
            stat_result = await get_instance(hass).async_add_executor_job(fn)
        except Exception:
            return _error("gateway_timeout", "Statistics call failed.", 504, request_id)

        _log(data, token, request_id=request_id, method="GET", resource=resource,
             outcome="allowed", client_ip=client_ip)
        return _json_response(stat_result, 200, request_id, rl_result)


class ATMConfigView(HomeAssistantView):
    """GET /api/atm/config - HA configuration (requires allow_config_read or pass_through)."""

    url = "/api/atm/config"
    name = "api:atm:config"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass = self.hass
        data: ATMData = hass.data[DOMAIN]
        request_id = generate_request_id()
        resource = "/api/atm/config"
        client_ip = _get_client_ip(request)

        result = await _get_authenticated_token(hass, request, data, request_id, resource)
        if isinstance(result, web.Response):
            return result
        token, rl_result = result

        if not token.allow_config_read and not token.pass_through:
            _log(data, token, request_id=request_id, method="GET", resource=resource,
                 outcome="denied", client_ip=client_ip)
            return _error("forbidden", "Forbidden.", 403, request_id)

        _log(data, token, request_id=request_id, method="GET", resource=resource,
             outcome="allowed", client_ip=client_ip)
        config_dict = hass.config.as_dict()
        # Strip ATM's own component entries so the token cannot enumerate our routes.
        config_dict["components"] = [
            c for c in config_dict.get("components", [])
            if c != DOMAIN and not c.startswith(DOMAIN + ".")
        ]
        return _json_response(config_dict, 200, request_id, rl_result)


class ATMTemplateView(HomeAssistantView):
    """POST /api/atm/template - render a Jinja2 template against permitted entity state."""

    url = "/api/atm/template"
    name = "api:atm:template"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        hass = self.hass
        data: ATMData = hass.data[DOMAIN]
        request_id = generate_request_id()
        resource = "/api/atm/template"
        client_ip = _get_client_ip(request)

        result = await _get_authenticated_token(hass, request, data, request_id, resource)
        if isinstance(result, web.Response):
            return result
        token, rl_result = result

        if not token.allow_template_render and not token.pass_through:
            _log(data, token, request_id=request_id, method="POST", resource=resource,
                 outcome="denied", client_ip=client_ip)
            return _error("forbidden", "Forbidden.", 403, request_id)

        body = await _read_json_body(request, request_id)
        if isinstance(body, web.Response):
            return body

        template_str = body.get("template")
        if not template_str or not isinstance(template_str, str):
            return _error("invalid_request", "Missing or invalid 'template' field.", 400, request_id)

        try:
            from homeassistant.helpers import template as template_helper

            if token.pass_through:
                permitted = {
                    s.entity_id: s
                    for s in hass.states.async_all()
                    if s.entity_id.split(".")[0] not in BLOCKED_DOMAINS
                }
            else:
                permitted = {
                    s.entity_id: s
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
            })
        except Exception:
            return _error(
                "invalid_request",
                "Template rendering failed.",
                400,
                request_id,
                suggestions=["Check your template syntax."],
            )

        _log(data, token, request_id=request_id, method="POST", resource=resource,
             outcome="allowed", client_ip=client_ip)
        return _json_response({"rendered": str(rendered)}, 200, request_id, rl_result)


class ATMEventsView(HomeAssistantView):
    """GET /api/atm/events - HA event bus listener counts (requires allow_config_read)."""

    url = "/api/atm/events"
    name = "api:atm:events"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass = self.hass
        data: ATMData = hass.data[DOMAIN]
        request_id = generate_request_id()
        resource = "/api/atm/events"
        client_ip = _get_client_ip(request)

        result = await _get_authenticated_token(hass, request, data, request_id, resource)
        if isinstance(result, web.Response):
            return result
        token, rl_result = result

        if not token.allow_config_read and not token.pass_through:
            _log(data, token, request_id=request_id, method="GET", resource=resource,
                 outcome="denied", client_ip=client_ip)
            return _error("forbidden", "Forbidden.", 403, request_id)

        listeners = hass.bus.async_listeners()
        events = [{"event": k, "listener_count": v} for k, v in sorted(listeners.items())]

        _log(data, token, request_id=request_id, method="GET", resource=resource,
             outcome="allowed", client_ip=client_ip)
        return _json_response(events, 200, request_id, rl_result)


class ATMServicesView(HomeAssistantView):
    """GET /api/atm/services - list services in domains the token has WRITE access to."""

    url = "/api/atm/services"
    name = "api:atm:services"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass = self.hass
        data: ATMData = hass.data[DOMAIN]
        request_id = generate_request_id()
        resource = "/api/atm/services"
        client_ip = _get_client_ip(request)

        result = await _get_authenticated_token(hass, request, data, request_id, resource)
        if isinstance(result, web.Response):
            return result
        token, rl_result = result

        all_services = hass.services.async_services()

        if token.pass_through:
            from .const import BLOCKED_DOMAINS
            filtered = {
                domain: svcs
                for domain, svcs in all_services.items()
                if domain not in BLOCKED_DOMAINS
            }
        else:
            from homeassistant.helpers import entity_registry as _er
            writable_domains: set[str] = set()
            for domain_name, node in token.permissions.domains.items():
                if node.state == "GREEN":
                    writable_domains.add(domain_name)
            for eid, node in token.permissions.entities.items():
                if node.state == "GREEN":
                    writable_domains.add(eid.split(".")[0])
            if token.permissions.devices:
                _er_reg = _er.async_get(hass)
                for device_id_key, node in token.permissions.devices.items():
                    if node.state == "GREEN":
                        for entry in _er_reg.entities.values():
                            if entry.device_id == device_id_key and not entry.disabled_by:
                                writable_domains.add(entry.domain)
            filtered = {
                domain: svcs
                for domain, svcs in all_services.items()
                if domain in writable_domains
            }

        output = [
            {
                "domain": domain,
                "services": {
                    name: (desc.as_dict() if hasattr(desc, "as_dict") else desc)
                    for name, desc in svcs.items()
                },
            }
            for domain, svcs in sorted(filtered.items())
        ]

        _log(data, token, request_id=request_id, method="GET", resource=resource,
             outcome="allowed", client_ip=client_ip)
        return _json_response(output, 200, request_id, rl_result)


ALL_VIEWS: list[type[HomeAssistantView]] = [
    ATMRootView,
    ATMStatesView,
    ATMStateView,
    ATMServiceView,
    ATMHistoryView,
    ATMStatisticsView,
    ATMConfigView,
    ATMTemplateView,
    ATMEventsView,
    ATMServicesView,
]

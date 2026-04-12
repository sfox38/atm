"""Admin API views for the ATM integration."""

from __future__ import annotations

import asyncio
import functools
import json
import uuid
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.const import KEY_HASS_USER
from homeassistant.util.dt import parse_datetime, utcnow

from .const import ATM_VERSION, BLOCKED_DOMAINS, DOMAIN, MAX_REQUEST_BODY_BYTES, TOKEN_NAME_REGEX
from .data import ATMData
from .helpers import terminate_token_connections, token_name_slug
from .policy_engine import Permission, filter_entities_for_token, resolve
from .token_store import PermissionTree, PermissionNode, _VALID_NODE_STATES


def _err(code: str, message: str, status: int) -> web.Response:
    """Return a JSON error response with a unique X-ATM-Request-ID header."""
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps({"error": code, "message": message}),
        headers={"X-ATM-Request-ID": str(uuid.uuid4())},
    )


def _ok(body: Any, status: int = 200) -> web.Response:
    """Return a JSON success response with a unique X-ATM-Request-ID header."""
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps(body),
        headers={"X-ATM-Request-ID": str(uuid.uuid4())},
    )


def _check_admin(request: web.Request) -> web.Response | None:
    """Return a 403 response if the request user is not an HA admin, else None."""
    user = request.get(KEY_HASS_USER)
    if not user or not user.is_admin:
        return _err("forbidden", "Admin access required.", 403)
    return None


def require_admin(method):
    """Decorator for HomeAssistantView methods that require HA admin privileges."""
    @functools.wraps(method)
    async def wrapper(self, request: web.Request, **kwargs):
        err = _check_admin(request)
        if err:
            return err
        return await method(self, request, **kwargs)
    return wrapper


async def _read_body(request: web.Request) -> dict | web.Response:
    """Read and parse the request body as a JSON object.

    Returns an empty dict for requests with no body. Returns an error response
    on read failure, invalid JSON, or a non-object body.
    """
    if request.content_length is not None and request.content_length > MAX_REQUEST_BODY_BYTES:
        return _err("request_too_large", "Request body too large.", 413)

    try:
        body_bytes = await request.read()
    except Exception:
        return _err("invalid_request", "Failed to read request body.", 400)

    if len(body_bytes) > MAX_REQUEST_BODY_BYTES:
        return _err("request_too_large", "Request body too large.", 413)

    if not body_bytes:
        return {}

    try:
        parsed = json.loads(body_bytes)
    except json.JSONDecodeError:
        return _err("invalid_request", "Invalid JSON body.", 400)

    if not isinstance(parsed, dict):
        return _err("invalid_request", "Request body must be a JSON object.", 400)

    return parsed


async def _build_entity_tree(hass: Any) -> dict:
    """Build a domain-keyed tree of all non-disabled, non-ATM entities.

    Pulls from the entity, device, and area registries. The result is cached
    in ATMData.entity_tree_cache and invalidated on registry change events.
    """
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)
    area_reg = ar.async_get(hass)

    tree: dict[str, dict] = {}

    for entry in entity_reg.entities.values():
        if entry.disabled_by is not None:
            continue

        entity_id = entry.entity_id
        domain = entity_id.split(".")[0]

        if domain in BLOCKED_DOMAINS:
            continue

        state = hass.states.get(entity_id)
        friendly_name = None
        if state:
            friendly_name = state.attributes.get("friendly_name") or state.name

        if domain not in tree:
            tree[domain] = {"devices": {}, "deviceless_entities": [], "entity_details": {}}

        area_id = entry.area_id
        if not area_id and entry.device_id:
            device = device_reg.async_get(entry.device_id)
            if device:
                area_id = device.area_id

        area_name = None
        if area_id:
            area = area_reg.async_get_area(area_id)
            area_name = area.name if area else None

        entity_info: dict[str, Any] = {
            "entity_id": entity_id,
            "friendly_name": friendly_name,
            "device_id": entry.device_id,
            "area_id": area_id,
            "area_name": area_name,
        }

        if entry.device_id:
            device_id = entry.device_id
            if device_id not in tree[domain]["devices"]:
                device = device_reg.async_get(device_id)
                if device:
                    d_area_id = device.area_id
                    d_area_name = None
                    if d_area_id:
                        da = area_reg.async_get_area(d_area_id)
                        d_area_name = da.name if da else None
                    tree[domain]["devices"][device_id] = {
                        "device_id": device_id,
                        "name": device.name_by_user or device.name or device_id,
                        "area_id": d_area_id,
                        "area_name": d_area_name,
                        "entities": [],
                    }
                else:
                    tree[domain]["devices"][device_id] = {
                        "device_id": device_id,
                        "name": device_id,
                        "area_id": None,
                        "area_name": None,
                        "entities": [],
                    }
            tree[domain]["devices"][device_id]["entities"].append(entity_id)
        else:
            tree[domain]["deviceless_entities"].append(entity_id)

        tree[domain]["entity_details"][entity_id] = entity_info

    return tree


def _build_resolution_path(entity_id: str, token: Any, hass: Any) -> list[dict]:
    """Return the ancestor chain and each node's state for a given entity/token pair.

    Used by the resolve admin endpoint to explain why an entity has a particular
    effective permission.
    """
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    er_reg = er.async_get(hass)
    dr_reg = dr.async_get(hass)

    entry = er_reg.async_get(entity_id)
    domain = entity_id.split(".")[0]

    path: list[dict] = [{"level": "global", "state": "GREY"}]

    domain_node = token.permissions.domains.get(domain)
    path.append({"level": f"domain:{domain}", "state": domain_node.state if domain_node else "GREY"})

    if entry and entry.device_id:
        device = dr_reg.async_get(entry.device_id)
        if device:
            device_name = device.name_by_user or device.name or entry.device_id
        else:
            device_name = entry.device_id
        device_node = token.permissions.devices.get(entry.device_id)
        path.append({"level": f"device:{device_name}", "state": device_node.state if device_node else "GREY"})

    entity_node = token.permissions.entities.get(entity_id)
    if entity_node is not None:
        path.append({"level": f"entity:{entity_id}", "state": entity_node.state})

    return path


class ATMAdminInfoView(HomeAssistantView):
    """GET /api/atm/admin/info - integration metadata."""

    url = "/api/atm/admin/info"
    name = "api:atm:admin:info"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request) -> web.Response:
        return _ok({"version": ATM_VERSION})


class ATMAdminArchivedTokensView(HomeAssistantView):
    """GET /api/atm/admin/tokens/archived - list all archived tokens."""

    url = "/api/atm/admin/tokens/archived"
    name = "api:atm:admin:archived_tokens"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request) -> web.Response:
        data: ATMData = self.hass.data[DOMAIN]
        archived = [t.to_dict() for t in data.store.list_archived()]
        return _ok(archived)


class ATMAdminArchivedTokenView(HomeAssistantView):
    """DELETE /api/atm/admin/tokens/archived/{token_id} - permanently delete an archived record."""

    url = "/api/atm/admin/tokens/archived/{token_id}"
    name = "api:atm:admin:archived_token"
    requires_auth = True

    @require_admin
    async def delete(self, request: web.Request, token_id: str) -> web.Response:
        data: ATMData = self.hass.data[DOMAIN]
        deleted = await data.store.async_delete_archived(token_id)
        if not deleted:
            return _err("not_found", "Archived token not found.", 404)
        return web.Response(status=204)


class ATMAdminTokensView(HomeAssistantView):
    """GET /api/atm/admin/tokens - list active tokens.
    POST /api/atm/admin/tokens - create a new token.
    """

    url = "/api/atm/admin/tokens"
    name = "api:atm:admin:tokens"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request) -> web.Response:
        data: ATMData = self.hass.data[DOMAIN]
        tokens = [t.to_dict() for t in data.store.list_tokens()]
        return _ok(tokens)

    @require_admin
    async def post(self, request: web.Request) -> web.Response:

        hass = self.hass
        data: ATMData = hass.data[DOMAIN]
        user = request[KEY_HASS_USER]

        body = await _read_body(request)
        if isinstance(body, web.Response):
            return body

        name = body.get("name")
        if not name or not isinstance(name, str):
            return _err("invalid_request", "name is required.", 400)
        if not TOKEN_NAME_REGEX.match(name):
            return _err("invalid_request", "name does not match required pattern.", 400)
        if data.store.name_slug_exists(name):
            return _err("invalid_request", "A token with that name (or equivalent slug) already exists.", 409)

        pass_through = bool(body.get("pass_through", False))
        if pass_through and not body.get("confirm_pass_through"):
            return _err("invalid_request", "confirm_pass_through: true is required when enabling pass_through.", 400)

        expires_at = None
        if "expires_at" in body:
            expires_at = parse_datetime(body["expires_at"])
            if expires_at is None:
                return _err("invalid_request", "Invalid expires_at datetime.", 400)

        try:
            rate_limit_requests = int(body.get("rate_limit_requests", 60))
            rate_limit_burst = int(body.get("rate_limit_burst", 10))
        except (TypeError, ValueError):
            return _err("invalid_request", "rate_limit_requests and rate_limit_burst must be integers.", 400)

        if rate_limit_requests < 0 or rate_limit_burst < 0:
            return _err("invalid_request", "rate_limit_requests and rate_limit_burst must be non-negative.", 400)

        record, raw_token = await data.store.async_create_token(
            name=name,
            created_by=user.id,
            expires_at=expires_at,
            pass_through=pass_through,
            rate_limit_requests=rate_limit_requests,
            rate_limit_burst=rate_limit_burst,
        )

        if data.async_on_token_created:
            await data.async_on_token_created(record)

        # raw_token is included once in the creation response and never again.
        response_body = record.to_dict()
        response_body["token"] = raw_token
        return _ok(response_body, status=201)


class ATMAdminTokenView(HomeAssistantView):
    """GET/PATCH/DELETE /api/atm/admin/tokens/{token_id} - manage a single token."""

    url = "/api/atm/admin/tokens/{token_id}"
    name = "api:atm:admin:token"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request, token_id: str) -> web.Response:
        data: ATMData = self.hass.data[DOMAIN]
        token = data.store.get_token_by_id(token_id)
        if token is None:
            return _err("not_found", "Token not found.", 404)
        return _ok(token.to_dict())

    @require_admin
    async def patch(self, request: web.Request, token_id: str) -> web.Response:

        data: ATMData = self.hass.data[DOMAIN]

        body = await _read_body(request)
        if isinstance(body, web.Response):
            return body

        if "name" in body or "expires_at" in body:
            return _err("invalid_request", "name and expires_at are immutable after token creation.", 400)

        async with data.store.async_lock:
            token = data.store.get_token_by_id(token_id)
            if token is None:
                return _err("not_found", "Token not found.", 404)

            if "pass_through" in body:
                enabling = bool(body["pass_through"])
                if enabling and not token.pass_through and not body.get("confirm_pass_through"):
                    return _err("invalid_request", "confirm_pass_through: true is required when enabling pass_through.", 400)

            patchable = {
                k: v for k, v in body.items()
                if k in ("pass_through", "rate_limit_requests", "rate_limit_burst",
                         "allow_automation_write", "allow_config_read",
                         "allow_template_render", "allow_restart")
            }
            for rl_field in ("rate_limit_requests", "rate_limit_burst"):
                if rl_field in patchable:
                    try:
                        patchable[rl_field] = int(patchable[rl_field])
                    except (TypeError, ValueError):
                        return _err("invalid_request", f"{rl_field} must be an integer.", 400)
                    if patchable[rl_field] < 0:
                        return _err("invalid_request", f"{rl_field} must be non-negative.", 400)
            updated = await data.store.async_patch_token(token_id, **patchable)

        return _ok(updated.to_dict())

    @require_admin
    async def delete(self, request: web.Request, token_id: str) -> web.Response:
        """Revoke a token. Archives it, terminates its SSE connections, fires the bus event."""

        hass = self.hass
        data: ATMData = hass.data[DOMAIN]
        user = request[KEY_HASS_USER]

        async with data.store.async_lock:
            token = data.store.get_token_by_id(token_id)
            if token is None:
                return _err("not_found", "Token not found.", 404)

            token_name = token.name
            now = utcnow()

            archived = await data.store.async_archive_token(token_id, revoked=True, revoked_at=now)
            if archived is None:
                return _err("not_found", "Token not found.", 404)

        await terminate_token_connections(token_id, data.sse_connections)
        data.rate_limiter.destroy(token_id)
        data.rate_limit_notified.pop(token_id, None)
        data.token_counters.pop(token_id, None)
        from .helpers import cancel_expiry_timer
        cancel_expiry_timer(data, token_id)

        hass.bus.async_fire("atm_token_revoked", {
            "token_id": token_id,
            "token_name": token_name,
            "revoked_by": user.id,
            "timestamp": now.isoformat(),
        })

        slug = token_name_slug(token_name)
        if data.async_on_token_archived:
            await data.async_on_token_archived(slug)

        return web.Response(status=204)


class ATMAdminPermissionsView(HomeAssistantView):
    """GET/PUT /api/atm/admin/tokens/{token_id}/permissions - read or replace the full permission tree."""

    url = "/api/atm/admin/tokens/{token_id}/permissions"
    name = "api:atm:admin:permissions"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request, token_id: str) -> web.Response:
        data: ATMData = self.hass.data[DOMAIN]
        token = data.store.get_token_by_id(token_id)
        if token is None:
            return _err("not_found", "Token not found.", 404)
        return _ok(token.permissions.to_dict())

    @require_admin
    async def put(self, request: web.Request, token_id: str) -> web.Response:

        data: ATMData = self.hass.data[DOMAIN]

        body = await _read_body(request)
        if isinstance(body, web.Response):
            return body

        try:
            new_tree = PermissionTree.from_dict(body)
        except Exception:
            return _err("invalid_request", "Invalid permission tree structure.", 400)

        async with data.store.async_lock:
            token = data.store.get_token_by_id(token_id)
            if token is None:
                return _err("not_found", "Token not found.", 404)

            updated = await data.store.async_set_permissions(token_id, new_tree)
        return _ok(updated.permissions.to_dict())


class ATMAdminPermissionDomainView(HomeAssistantView):
    """PATCH /api/atm/admin/tokens/{token_id}/permissions/domains/{node_id}."""

    url = "/api/atm/admin/tokens/{token_id}/permissions/domains/{node_id}"
    name = "api:atm:admin:permission_domain"
    requires_auth = True

    async def patch(self, request: web.Request, token_id: str, node_id: str) -> web.Response:
        return await _patch_permission_node(request, self.hass, token_id, "domains", node_id)


class ATMAdminPermissionDeviceView(HomeAssistantView):
    """PATCH /api/atm/admin/tokens/{token_id}/permissions/devices/{node_id}."""

    url = "/api/atm/admin/tokens/{token_id}/permissions/devices/{node_id}"
    name = "api:atm:admin:permission_device"
    requires_auth = True

    async def patch(self, request: web.Request, token_id: str, node_id: str) -> web.Response:
        return await _patch_permission_node(request, self.hass, token_id, "devices", node_id)


class ATMAdminPermissionEntityView(HomeAssistantView):
    """PATCH /api/atm/admin/tokens/{token_id}/permissions/entities/{node_id}."""

    url = "/api/atm/admin/tokens/{token_id}/permissions/entities/{node_id}"
    name = "api:atm:admin:permission_entity"
    requires_auth = True

    async def patch(self, request: web.Request, token_id: str, node_id: str) -> web.Response:
        return await _patch_permission_node(request, self.hass, token_id, "entities", node_id)


async def _patch_permission_node(
    request: web.Request,
    hass: Any,
    token_id: str,
    node_type: str,
    node_id: str,
) -> web.Response:
    """Shared handler for PATCH on domain/device/entity permission nodes."""
    err = _check_admin(request)
    if err:
        return err

    data: ATMData = hass.data[DOMAIN]

    body = await _read_body(request)
    if isinstance(body, web.Response):
        return body

    state = body.get("state")
    if state not in _VALID_NODE_STATES:
        return _err("invalid_request", f"state must be one of: {', '.join(sorted(_VALID_NODE_STATES))}.", 400)

    hint = body.get("hint")
    if hint is not None and not isinstance(hint, str):
        return _err("invalid_request", "hint must be a string.", 400)

    async with data.store.async_lock:
        token = data.store.get_token_by_id(token_id)
        if token is None:
            return _err("not_found", "Token not found.", 404)

        updated = await data.store.async_patch_permission_node(
            token_id, node_type, node_id, state, hint
        )

    return _ok(updated.permissions.to_dict())


class ATMAdminResolveView(HomeAssistantView):
    """GET /api/atm/admin/tokens/{token_id}/resolve/{entity_id} - explain effective permission."""

    url = "/api/atm/admin/tokens/{token_id}/resolve/{entity_id}"
    name = "api:atm:admin:resolve"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request, token_id: str, entity_id: str) -> web.Response:
        hass = self.hass
        data: ATMData = hass.data[DOMAIN]
        token = data.store.get_token_by_id(token_id)
        if token is None:
            return _err("not_found", "Token not found.", 404)

        perm = resolve(entity_id, token, hass)
        resolution_path = _build_resolution_path(entity_id, token, hass)

        effective_map = {
            Permission.WRITE: "WRITE",
            Permission.READ: "READ",
            Permission.DENY: "DENY",
            Permission.NO_ACCESS: "NO_ACCESS",
            Permission.NOT_FOUND: "NOT_FOUND",
        }

        return _ok({
            "entity_id": entity_id,
            "resolution_path": resolution_path,
            "effective": effective_map.get(perm, "NO_ACCESS"),
        })


class ATMAdminScopeView(HomeAssistantView):
    """GET /api/atm/admin/tokens/{token_id}/scope - enumerate all readable/writable entities."""

    url = "/api/atm/admin/tokens/{token_id}/scope"
    name = "api:atm:admin:scope"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request, token_id: str) -> web.Response:
        hass = self.hass
        data: ATMData = hass.data[DOMAIN]
        token = data.store.get_token_by_id(token_id)
        if token is None:
            return _err("not_found", "Token not found.", 404)

        all_states = hass.states.async_all()
        readable: list[str] = []
        writable: list[str] = []

        for state in all_states:
            eid = state.entity_id
            perm = resolve(eid, token, hass)
            if perm == Permission.WRITE:
                readable.append(eid)
                writable.append(eid)
            elif perm == Permission.READ:
                readable.append(eid)

        return _ok({
            "token_id": token_id,
            "token_name": token.name,
            "readable": sorted(readable),
            "writable": sorted(writable),
            "capability_flags": {
                "allow_config_read": token.allow_config_read,
                "allow_automation_write": token.allow_automation_write,
                "allow_template_render": token.allow_template_render,
                "allow_restart": token.allow_restart,
            },
        })


class ATMAdminEntityTreeView(HomeAssistantView):
    """GET /api/atm/admin/entities - return (cached) entity tree for the permission UI."""

    url = "/api/atm/admin/entities"
    name = "api:atm:admin:entities"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request) -> web.Response:
        hass = self.hass
        data: ATMData = hass.data[DOMAIN]

        if request.query.get("force_reload"):
            data.entity_tree_cache_valid = False

        async with data.entity_tree_lock:
            if not data.entity_tree_cache_valid or data.entity_tree_cache is None:
                data.entity_tree_cache = await _build_entity_tree(hass)
                data.entity_tree_cache_valid = True

        return _ok(data.entity_tree_cache)


class ATMAdminTokenStatsView(HomeAssistantView):
    """GET /api/atm/admin/tokens/{token_id}/stats - in-memory counters for one token."""

    url = "/api/atm/admin/tokens/{token_id}/stats"
    name = "api:atm:admin:token_stats"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request, token_id: str) -> web.Response:
        data: ATMData = self.hass.data[DOMAIN]
        token = data.store.get_token_by_id(token_id)
        if token is None:
            return _err("not_found", "Token not found.", 404)

        counters = data.token_counters.get(token_id, {
            "request_count": 0,
            "denied_count": 0,
            "rate_limit_hits": 0,
        })

        last_used = token.last_used_at.isoformat() if token.last_used_at else None

        return _ok({
            "token_id": token_id,
            "token_name": token.name,
            "request_count": counters["request_count"],
            "denied_count": counters["denied_count"],
            "rate_limit_hits": counters["rate_limit_hits"],
            "last_used_at": last_used,
            "status": "active",
        })


class ATMAdminTokenAuditView(HomeAssistantView):
    """GET /api/atm/admin/tokens/{token_id}/audit - paginated audit log for one token."""

    url = "/api/atm/admin/tokens/{token_id}/audit"
    name = "api:atm:admin:token_audit"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request, token_id: str) -> web.Response:
        data: ATMData = self.hass.data[DOMAIN]
        token = data.store.get_token_by_id(token_id)
        if token is None:
            return _err("not_found", "Token not found.", 404)

        try:
            limit = min(int(request.query.get("limit", 100)), 500)
            offset = max(int(request.query.get("offset", 0)), 0)
        except ValueError:
            return _err("invalid_request", "Invalid pagination parameters.", 400)

        outcome_filter = request.query.get("outcome")
        ip_filter = request.query.get("ip")

        entries = data.audit.query(
            token_id=token_id,
            outcome=outcome_filter,
            client_ip=ip_filter,
            limit=limit,
            offset=offset,
        )
        return _ok([e.to_dict() for e in entries])


class ATMAdminAuditView(HomeAssistantView):
    """GET /api/atm/admin/audit - paginated global audit log with optional filters."""

    url = "/api/atm/admin/audit"
    name = "api:atm:admin:audit"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request) -> web.Response:
        data: ATMData = self.hass.data[DOMAIN]

        try:
            limit = min(int(request.query.get("limit", 100)), 500)
            offset = max(int(request.query.get("offset", 0)), 0)
        except ValueError:
            return _err("invalid_request", "Invalid pagination parameters.", 400)

        token_id_filter = request.query.get("token_id")
        outcome_filter = request.query.get("outcome")
        ip_filter = request.query.get("ip")

        entries = data.audit.query(
            token_id=token_id_filter,
            outcome=outcome_filter,
            client_ip=ip_filter,
            limit=limit,
            offset=offset,
        )
        return _ok([e.to_dict() for e in entries])


class ATMAdminSettingsView(HomeAssistantView):
    """GET/PATCH /api/atm/admin/settings - read or update global integration settings."""

    url = "/api/atm/admin/settings"
    name = "api:atm:admin:settings"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request) -> web.Response:
        data: ATMData = self.hass.data[DOMAIN]
        return _ok(data.store.get_settings().to_dict())

    @require_admin
    async def patch(self, request: web.Request) -> web.Response:

        data: ATMData = self.hass.data[DOMAIN]

        body = await _read_body(request)
        if isinstance(body, web.Response):
            return body

        _VALID_FLUSH_INTERVALS = frozenset({0, 5, 10, 15, 30, 60})
        _VALID_LOG_MAXLENS = frozenset({100, 1000, 5000, 10000})

        patchable = {
            k: v for k, v in body.items()
            if k in (
                "kill_switch", "disable_all_logging", "log_allowed", "log_denied",
                "log_rate_limited", "log_entity_names", "log_client_ip", "notify_on_rate_limit",
                "audit_flush_interval", "audit_log_maxlen",
            )
        }

        if "audit_flush_interval" in patchable:
            try:
                patchable["audit_flush_interval"] = int(patchable["audit_flush_interval"])
            except (TypeError, ValueError):
                return _err("invalid_request", "audit_flush_interval must be an integer.", 400)
            if patchable["audit_flush_interval"] not in _VALID_FLUSH_INTERVALS:
                return _err("invalid_request", f"audit_flush_interval must be one of: {sorted(_VALID_FLUSH_INTERVALS)}.", 400)

        if "audit_log_maxlen" in patchable:
            try:
                patchable["audit_log_maxlen"] = int(patchable["audit_log_maxlen"])
            except (TypeError, ValueError):
                return _err("invalid_request", "audit_log_maxlen must be an integer.", 400)
            if patchable["audit_log_maxlen"] not in _VALID_LOG_MAXLENS:
                return _err("invalid_request", f"audit_log_maxlen must be one of: {sorted(_VALID_LOG_MAXLENS)}.", 400)

        old_kill_switch = data.store.get_settings().kill_switch

        async with data.store.async_lock:
            updated = await data.store.async_patch_settings(**patchable)

        if "audit_log_maxlen" in patchable:
            data.audit.resize(patchable["audit_log_maxlen"])

        if "kill_switch" in patchable:
            new_kill_switch = updated.kill_switch
            if not old_kill_switch and new_kill_switch:
                # Kill switch just activated: terminate all open SSE connections.
                for token_id in list(data.sse_connections.keys()):
                    await terminate_token_connections(token_id, data.sse_connections)

        return _ok(updated.to_dict())


class ATMAdminWipeView(HomeAssistantView):
    """DELETE /api/atm/admin/wipe - wipe all tokens, audit log, and settings."""

    url = "/api/atm/admin/wipe"
    name = "api:atm:admin:wipe"
    requires_auth = True

    @require_admin
    async def delete(self, request: web.Request) -> web.Response:
        body = await _read_body(request)
        if isinstance(body, web.Response):
            return body

        if body.get("confirm") != "WIPE":
            return _err("invalid_request", 'confirm must be "WIPE".', 400)

        hass = self.hass
        data: ATMData = hass.data[DOMAIN]

        for token_id in list(data.sse_connections.keys()):
            await terminate_token_connections(token_id, data.sse_connections)

        data.rate_limiter.destroy_all()
        data.rate_limit_notified.clear()
        data.token_counters.clear()
        await data.audit.async_wipe()

        active_slugs = [token_name_slug(t.name) for t in data.store.list_tokens()]
        from .helpers import cancel_expiry_timer
        for _tid in list(data.expiry_timers):
            cancel_expiry_timer(data, _tid)
        await data.store.async_wipe()

        if data.async_on_token_archived:
            await asyncio.gather(*[data.async_on_token_archived(slug) for slug in active_slugs])

        return web.Response(status=204)


ALL_ADMIN_VIEWS: list[type[HomeAssistantView]] = [
    ATMAdminInfoView,
    ATMAdminArchivedTokensView,
    ATMAdminArchivedTokenView,
    ATMAdminTokensView,
    ATMAdminTokenView,
    ATMAdminPermissionsView,
    ATMAdminPermissionDomainView,
    ATMAdminPermissionDeviceView,
    ATMAdminPermissionEntityView,
    ATMAdminResolveView,
    ATMAdminScopeView,
    ATMAdminEntityTreeView,
    ATMAdminTokenStatsView,
    ATMAdminTokenAuditView,
    ATMAdminAuditView,
    ATMAdminSettingsView,
    ATMAdminWipeView,
]

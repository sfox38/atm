"""Shared helpers used by multiple ATM views."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util.dt import parse_datetime, utcnow

from .const import MAX_REQUEST_BODY_BYTES, SENSITIVE_ATTRIBUTES, TOKEN_LENGTH, TOKEN_PREFIX
from .policy_engine import parse_relative_time
from .token_store import token_name_slug

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import ATMData
    from .rate_limiter import RateLimitResult
    from .token_store import TokenRecord


def build_error_response(
    code: str,
    message: str,
    status: int,
    request_id: str,
    suggestions: list[str] | None = None,
) -> web.Response:
    """Return a JSON error response with an X-ATM-Request-ID header."""
    body: dict[str, Any] = {"error": code, "message": message}
    if suggestions:
        body["suggestions"] = suggestions
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps(body),
        headers={"X-ATM-Request-ID": request_id},
    )


def get_client_ip(request: web.Request) -> str:
    """Return the remote IP address, or an empty string if unavailable."""
    return request.remote or ""


def log_request(
    data: ATMData,
    token: TokenRecord,
    *,
    request_id: str,
    method: str,
    resource: str,
    outcome: str,
    client_ip: str,
) -> None:
    """Record an audit entry and update in-memory token counters."""
    data.audit.record(
        request_id=request_id,
        token_id=token.id,
        token_name=token.name,
        method=method,
        resource=resource,
        outcome=outcome,
        client_ip=client_ip,
        settings=data.store.get_settings(),
        pass_through=token.pass_through,
    )
    update_token_counter(data, token.id, outcome)


def fire_rate_limit_events(hass: HomeAssistant, data: ATMData, token: TokenRecord) -> None:
    """Fire the atm_rate_limited bus event and optional persistent notification.

    Throttled to at most once per token per minute to avoid event floods.
    """
    now_mono = time.monotonic()
    last = data.rate_limit_notified.get(token.id, 0.0)
    if now_mono - last >= 60.0:
        data.rate_limit_notified[token.id] = now_mono
        hass.bus.async_fire("atm_rate_limited", {
            "token_id": token.id,
            "token_name": token.name,
            "timestamp": utcnow().isoformat(),
        })
        settings = data.store.get_settings()
        if settings.notify_on_rate_limit:
            hass.async_create_task(
                hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "message": f"ATM: token '{token.name}' has hit its rate limit.",
                        "title": "ATM Alert",
                        "notification_id": f"atm_rate_limit_{token.id}",
                    },
                )
            )


async def read_json_body(request: web.Request, request_id: str) -> dict | web.Response:
    """Read and size-check the request body, return a parsed dict or an error response."""
    if request.content_length is not None and request.content_length > MAX_REQUEST_BODY_BYTES:
        return build_error_response("request_too_large", "Request body too large.", 413, request_id)

    try:
        body_bytes = await request.read()
    except Exception:
        return build_error_response("invalid_request", "Failed to read request body.", 400, request_id)

    if len(body_bytes) > MAX_REQUEST_BODY_BYTES:
        return build_error_response("request_too_large", "Request body too large.", 413, request_id)

    if not body_bytes:
        return {}

    try:
        parsed = json.loads(body_bytes)
    except json.JSONDecodeError:
        return build_error_response("invalid_request", "Invalid JSON body.", 400, request_id)

    if not isinstance(parsed, dict):
        return build_error_response("invalid_request", "Request body must be a JSON object.", 400, request_id)

    return parsed


def parse_time_param(value: str) -> Any:
    """Parse a relative time string or ISO timestamp. Raises ValueError for unknown formats."""
    try:
        return parse_relative_time(value)
    except ValueError:
        pass
    dt = parse_datetime(value)
    if dt is None:
        raise ValueError(f"Unrecognized time format: {value!r}")
    return dt


async def get_authenticated_token(
    hass: HomeAssistant,
    request: web.Request,
    data: ATMData,
    request_id: str,
    resource: str,
) -> tuple[TokenRecord, RateLimitResult] | web.Response:
    """Validate the ATM bearer token and check rate limits.

    Returns (token, rl_result) on success, or an aiohttp Response on failure.
    Checks for kill switch, query-param token leakage, format pre-validation,
    hash lookup, revocation, expiry, and rate limits in that order.
    """
    if data.store.get_settings().kill_switch:
        return build_error_response("service_unavailable", "Service unavailable.", 503, request_id)

    _401 = build_error_response("unauthorized", "Unauthorized.", 401, request_id)
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

    rl_result = data.rate_limiter.check(
        token.id,
        token.rate_limit_requests,
        token.rate_limit_burst,
    )

    if not rl_result.allowed:
        fire_rate_limit_events(hass, data, token)
        log_request(
            data,
            token,
            request_id=request_id,
            method=request.method,
            resource=resource,
            outcome="rate_limited",
            client_ip=get_client_ip(request),
        )
        resp = build_error_response("rate_limited", "Rate limit exceeded.", 429, request_id)
        resp.headers["Retry-After"] = str(rl_result.retry_after)
        return resp

    data.store.update_last_used(token.id, utcnow())
    return token, rl_result


def cancel_expiry_timer(data: ATMData, token_id: str) -> None:
    """Cancel and remove the pending expiry timer for a token, if one exists."""
    cancel = data.expiry_timers.pop(token_id, None)
    if cancel is not None:
        cancel()


def schedule_expiry_timer(hass: HomeAssistant, data: ATMData, token: TokenRecord) -> None:
    """Schedule a timer to archive a token at its expiry time.

    If the token has no expiry, or has already expired, no timer is scheduled.
    Any previously registered timer for this token is cancelled first.
    """
    if token.expires_at is None:
        return
    cancel_expiry_timer(data, token.id)
    delay = (token.expires_at - utcnow()).total_seconds()
    if delay <= 0:
        return

    @callback
    def _on_expiry(_now=None) -> None:
        data.expiry_timers.pop(token.id, None)
        hass.async_create_background_task(
            archive_expired_token(hass, data, token),
            f"atm_expire_{token.id}",
        )

    data.expiry_timers[token.id] = async_call_later(hass, delay, _on_expiry)


async def archive_expired_token(
    hass: HomeAssistant,
    data: ATMData,
    token: TokenRecord,
) -> None:
    """Move an expired token to the archive and perform full cleanup.

    Archives the record to storage, terminates SSE connections, destroys
    rate limiter and counter state, fires the atm_token_expired bus event,
    and removes sensor entities.
    """
    now = utcnow()
    slug = token_name_slug(token.name)
    cancel_expiry_timer(data, token.id)
    archived = await data.store.async_archive_token(token.id, revoked=False, revoked_at=now)
    if archived is None:
        return
    await terminate_token_connections(token.id, data.sse_connections)
    data.rate_limiter.destroy(token.id)
    data.rate_limit_notified.pop(token.id, None)
    data.token_counters.pop(token.id, None)
    hass.bus.async_fire("atm_token_expired", {
        "token_id": token.id,
        "token_name": token.name,
        "timestamp": now.isoformat(),
    })
    if data.async_on_token_archived:
        await data.async_on_token_archived(slug)


async def terminate_token_connections(
    token_id: str,
    sse_connections: dict[str, set[asyncio.Queue]],
) -> None:
    """Signal all SSE queues for a token to close and remove them from the registry.

    Puts None (the sentinel) into each queue so the SSE loop exits cleanly.
    """
    queues = sse_connections.pop(token_id, set())
    for queue in queues:
        try:
            queue.put_nowait(None)
        except asyncio.QueueFull:
            # Queue is at capacity (slow/disconnected client). Evict one message to
            # make room for the sentinel so the SSE loop exits without blocking.
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            queue.put_nowait(None)


class _ContextProxy(dict):
    """Dict subclass that also supports attribute access.

    Used by ScrubbedState.context so templates can use both context.id and
    context | tojson without TypeError. Behaves as a plain dict for json.dumps().
    """

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


class ScrubbedState:
    """Lightweight State wrapper that strips sensitive attributes for use in template sandboxes."""

    def __init__(self, raw: Any) -> None:
        self.entity_id = raw.entity_id
        self.state = raw.state
        self.attributes = {k: v for k, v in raw.attributes.items() if k not in SENSITIVE_ATTRIBUTES}
        self.last_updated = getattr(raw, "last_updated", None)
        self.last_changed = getattr(raw, "last_changed", None)
        # Strip user_id from context to prevent HA user ID enumeration via templates.
        ctx = getattr(raw, "context", None)
        if ctx is not None:
            self.context = _ContextProxy({
                "id": getattr(ctx, "id", None),
                "parent_id": getattr(ctx, "parent_id", None),
                "user_id": None,
            })
        else:
            self.context = None

    @property
    def domain(self) -> str:
        return self.entity_id.split(".")[0]

    @property
    def object_id(self) -> str:
        return self.entity_id.split(".", 1)[1] if "." in self.entity_id else self.entity_id

    @property
    def name(self) -> str:
        friendly = self.attributes.get("friendly_name")
        if friendly:
            return str(friendly)
        return self.object_id.replace("_", " ").title()

    def as_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "state": self.state,
            "attributes": self.attributes,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "last_changed": self.last_changed.isoformat() if self.last_changed else None,
            "context": {
                "id": getattr(self.context, "id", None),
                "parent_id": getattr(self.context, "parent_id", None),
                "user_id": None,
            } if self.context is not None else None,
        }


class FilteredStates:
    """Callable proxy over a permitted-entity dict mimicking the HA template 'states' global.

    HA templates use 'states' as both a callable (states('sensor.foo')) and a
    domain-keyed accessor (states.light). A plain dict breaks the callable form,
    so this proxy implements both protocols while restricting access to permitted entities.
    """

    def __init__(self, permitted: dict) -> None:
        self._permitted = permitted

    def __call__(self, entity_id: str, default: str = "unknown") -> str:
        s = self._permitted.get(entity_id)
        return s.state if s is not None else default

    def __getitem__(self, entity_id: str):
        return self._permitted.get(entity_id)

    def __iter__(self):
        return iter(self._permitted.values())

    def __len__(self) -> int:
        return len(self._permitted)

    def __getattr__(self, domain: str):
        if domain.startswith("_"):
            raise AttributeError(domain)
        return {
            eid.split(".", 1)[1]: s
            for eid, s in self._permitted.items()
            if eid.split(".")[0] == domain
        }


def update_token_counter(data: ATMData, token_id: str, outcome: str) -> None:
    """Increment the in-memory request/denied/rate-limit counters for a token.

    Counters are initialised on first use and read by sensor.py and the admin stats view.
    """
    if token_id not in data.token_counters:
        data.token_counters[token_id] = {
            "request_count": 0,
            "denied_count": 0,
            "rate_limit_hits": 0,
        }
    counters = data.token_counters[token_id]
    counters["request_count"] += 1
    if outcome in ("denied", "not_found"):
        counters["denied_count"] += 1
    elif outcome == "rate_limited":
        counters["rate_limit_hits"] += 1

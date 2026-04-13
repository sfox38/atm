"""Permission resolution engine for ATM. No I/O."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util.dt import utcnow

from .const import BLOCKED_DOMAINS, SENSITIVE_ATTRIBUTES
from .token_store import TokenRecord


class Permission(str, Enum):
    WRITE = "write"
    READ = "read"
    DENY = "deny"
    NO_ACCESS = "no_access"
    NOT_FOUND = "not_found"


class EntityCreationNotPermitted(Exception):
    def __init__(self, entity_id: str) -> None:
        self.entity_id = entity_id
        super().__init__(
            f"Entity {entity_id!r} is not in the entity registry; "
            "ATM does not permit entity creation via service calls."
        )


_RELATIVE_TIME_RE = re.compile(r"^(\d+)(h|d|w|m)$")
_ENTITY_ID_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def resolve(entity_id: str, token: TokenRecord, hass: HomeAssistant) -> Permission:
    """Resolve effective permission for entity_id against a token.

    Return values:
        Permission.WRITE      - full access
        Permission.READ       - read-only access
        Permission.DENY       - explicitly denied; audit outcome: denied
        Permission.NO_ACCESS  - no grant found; audit outcome: denied
        Permission.NOT_FOUND  - ghost entity (not in states or registry); audit outcome: not_found

    Pass-through tokens return WRITE for all entities (after ATM blocklist check).
    The DUAL_GATE_SERVICES check is NOT performed here; it is the caller's responsibility.
    """
    registry = er.async_get(hass)

    # Resolve to canonical entity_id via entity registry
    entry = registry.async_get(entity_id)
    if entry:
        entity_id = entry.entity_id
        # Re-fetch entry for canonical ID so device_id lookup is authoritative.
        entry = registry.async_get(entity_id)

    domain = entity_id.split(".")[0]

    # Ghost check (before pass-through short-circuit so ghosts are never accessible)
    if hass.states.get(entity_id) is None and registry.async_get(entity_id) is None:
        return Permission.NOT_FOUND

    # ATM blocklist - applies even in pass-through mode
    if domain in BLOCKED_DOMAINS:
        return Permission.NO_ACCESS

    # Pass-through bypasses all entity permission resolution
    if token.pass_through:
        return Permission.WRITE

    permissions = token.permissions
    device_id = entry.device_id if entry else None

    entity_node = permissions.entities.get(entity_id)
    device_node = permissions.devices.get(device_id) if device_id else None
    domain_node = permissions.domains.get(domain)

    # Pass 1: RED check - walk entire ancestor chain before resolving any grant
    for node in (entity_node, device_node, domain_node):
        if node is not None and node.state == "RED":
            return Permission.DENY

    # Pass 2: most specific non-GREY grant
    for node in (entity_node, device_node, domain_node):
        if node is None:
            continue
        if node.state == "GREEN":
            return Permission.WRITE
        if node.state == "YELLOW":
            return Permission.READ

    return Permission.NO_ACCESS


def scrub_sensitive_attributes(state: State) -> dict[str, Any]:
    """Return a state dict with sensitive attributes removed."""
    d = state.as_dict()
    clean_attrs = {
        k: v for k, v in d.get("attributes", {}).items()
        if k not in SENSITIVE_ATTRIBUTES
    }
    return {**d, "attributes": clean_attrs}


def scrub_state_dict(d: dict) -> dict:
    """Return a copy of a raw state dict with sensitive attributes removed.

    Use this when the input is already a dict (e.g. from state history results).
    Use scrub_sensitive_attributes when working with State objects directly.
    """
    attrs = {k: v for k, v in d.get("attributes", {}).items() if k not in SENSITIVE_ATTRIBUTES}
    return {**d, "attributes": attrs}


def filter_entities_for_token(
    entities: list[State],
    token: TokenRecord,
    hass: HomeAssistant,
) -> list[dict[str, Any]]:
    """Filter a list of State objects to those accessible by token, scrub sensitive attributes.

    Always scrubs sensitive attributes and blocks the ATM domain, even in pass-through mode.
    """
    if token.pass_through:
        return [
            scrub_sensitive_attributes(e)
            for e in entities
            if e.entity_id.split(".")[0] not in BLOCKED_DOMAINS
        ]
    return [
        scrub_sensitive_attributes(e)
        for e in entities
        if resolve(e.entity_id, token, hass) in (Permission.READ, Permission.WRITE)
    ]


def expand_service_targets(
    *,
    entity_id: str | list[str] | None,
    device_id: str | list[str] | None,
    area_id: str | list[str] | None,
    service_domain: str,
    hass: HomeAssistant,
) -> tuple[set[str], list[str]]:
    """Expand service call targets without permission filtering or entity creation checks.

    Returns (device_area_candidates, explicit_entity_ids) where:
    - device_area_candidates: entity IDs from device/area/'all' expansion (deduplicated set)
    - explicit_entity_ids: entity IDs specified directly (not via 'all') that callers must
      validate against the entity registry before use

    Use resolve_service_targets for the full filtered result. Use this directly only when
    a raw count is needed (e.g. X-ATM-Entities-Requested header).
    """
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    candidates: set[str] = set()
    explicit_ids: list[str] = []

    if entity_id is not None:
        ids = [entity_id] if isinstance(entity_id, str) else list(entity_id)
        for eid in ids:
            if eid == "all":
                for state in hass.states.async_all():
                    if state.entity_id.split(".")[0] == service_domain:
                        candidates.add(state.entity_id)
            else:
                explicit_ids.append(eid)

    if device_id is not None:
        dids = [device_id] if isinstance(device_id, str) else list(device_id)
        for did in dids:
            for entry in entity_registry.entities.values():
                if (
                    entry.device_id == did
                    and entry.domain == service_domain
                    and not entry.disabled_by
                ):
                    candidates.add(entry.entity_id)

    if area_id is not None:
        aids = [area_id] if isinstance(area_id, str) else list(area_id)
        # Build indexes once to avoid O(A*E) and O(D*E) nested iteration.
        device_entity_index: dict[str, list[str]] = {}
        area_entity_index: dict[str, list[str]] = {}
        for entry in entity_registry.entities.values():
            if entry.domain == service_domain and not entry.disabled_by:
                if entry.device_id:
                    device_entity_index.setdefault(entry.device_id, []).append(entry.entity_id)
                if entry.area_id:
                    area_entity_index.setdefault(entry.area_id, []).append(entry.entity_id)
        for aid in aids:
            for eid in area_entity_index.get(aid, []):
                candidates.add(eid)
            for device in device_registry.devices.values():
                if device.area_id == aid:
                    for eid in device_entity_index.get(device.id, []):
                        candidates.add(eid)

    if entity_id is None and device_id is None and area_id is None:
        for state in hass.states.async_all():
            if state.entity_id.split(".")[0] == service_domain:
                candidates.add(state.entity_id)

    return candidates, explicit_ids


def resolve_service_targets(
    *,
    entity_id: str | list[str] | None = None,
    device_id: str | list[str] | None = None,
    area_id: str | list[str] | None = None,
    service_domain: str,
    token: TokenRecord,
    hass: HomeAssistant,
) -> list[str]:
    """Resolve service call targets to a WRITE-permitted, deduplicated entity_id list.

    Raises:
        EntityCreationNotPermitted: if an explicit entity_id is not in the entity registry.

    Returns an empty list when no entities pass permission filtering; the caller must
    return 403 in that case.

    ATM never passes device_id, area_id, or 'all' through to HA. This function
    always returns an explicit entity list.
    """
    entity_registry = er.async_get(hass)

    candidates, explicit_ids = expand_service_targets(
        entity_id=entity_id,
        device_id=device_id,
        area_id=area_id,
        service_domain=service_domain,
        hass=hass,
    )

    # Entity creation check for explicit entity_ids; raises immediately if any are not in registry
    for eid in explicit_ids:
        if entity_registry.async_get(eid) is None:
            raise EntityCreationNotPermitted(eid)
        candidates.add(eid)

    # Deduplicate while preserving order, then filter to WRITE-permitted entities
    seen: set[str] = set()
    permitted: list[str] = []
    for eid in candidates:
        if eid in seen:
            continue
        seen.add(eid)
        if resolve(eid, token, hass) == Permission.WRITE:
            permitted.append(eid)

    return permitted


def filter_service_response(
    response_data: Any,
    token: TokenRecord,
    hass: HomeAssistant,
    _depth: int = 0,
) -> Any:
    """Recursively redact entity IDs the token cannot access from service response data."""
    if _depth > 10:
        # Depth limit reached. Still redact entity ID strings, but truncate
        # containers to empty rather than returning their raw contents - a dict
        # or list at this depth could contain entity IDs at deeper levels that
        # would bypass redaction if returned as-is.
        if isinstance(response_data, str) and _ENTITY_ID_RE.match(response_data):
            perm = resolve(response_data, token, hass)
            if perm in (Permission.NO_ACCESS, Permission.DENY, Permission.NOT_FOUND):
                return "<redacted>"
            return response_data
        if isinstance(response_data, dict):
            return {}
        if isinstance(response_data, list):
            return []
        return response_data
    if isinstance(response_data, str):
        if _ENTITY_ID_RE.match(response_data):
            perm = resolve(response_data, token, hass)
            if perm in (Permission.NO_ACCESS, Permission.DENY, Permission.NOT_FOUND):
                return "<redacted>"
        return response_data
    if isinstance(response_data, dict):
        return {k: filter_service_response(v, token, hass, _depth + 1) for k, v in response_data.items()}
    if isinstance(response_data, list):
        return [filter_service_response(item, token, hass, _depth + 1) for item in response_data]
    return response_data


def get_effective_hint(token: TokenRecord, entity_id: str, hass: HomeAssistant) -> str | None:
    """Return the most specific hint for an entity, checking entity then device then domain nodes.

    Returns None if no hint is configured at any level in the ancestor chain.
    """
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


def template_blocklist_vars() -> dict:
    """Return a variables dict that shadows HA template globals to block entity enumeration.

    Pass as **template_blocklist_vars() when building the variables dict for
    Template.async_render(). Jinja2 local variables shadow globals of the same name,
    so these stubs override HA's built-in functions that could bypass ATM filtering.
    """
    return {
        "integration_entities": lambda *a, **kw: [],
        "area_entities": lambda *a, **kw: [],
        "area_devices": lambda *a, **kw: [],
        "device_entities": lambda *a, **kw: [],
        "expand": lambda *a, **kw: [],
        "label_entities": lambda *a, **kw: [],
        "label_areas": lambda *a, **kw: [],
        "floor_entities": lambda *a, **kw: [],
        "floor_areas": lambda *a, **kw: [],
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
    }


def parse_relative_time(value: str) -> datetime:
    """Parse a relative time string to a UTC datetime.

    Supported formats: '24h' (hours), '7d' (days), '2w' (weeks), '1m' (30-day months).
    Raises ValueError for unrecognized formats.
    """
    match = _RELATIVE_TIME_RE.match(value.strip())
    if not match:
        raise ValueError(f"Unrecognized relative time format: {value!r}")
    n = int(match.group(1))
    unit = match.group(2)
    if unit == "h":
        delta = timedelta(hours=n)
    elif unit == "d":
        delta = timedelta(days=n)
    elif unit == "w":
        delta = timedelta(weeks=n)
    else:
        delta = timedelta(days=30 * n)
    return utcnow() - delta


def resolve_intent_entities(
    hass: HomeAssistant,
    token: TokenRecord,
    *,
    domains: list[str] | None = None,
    device_classes: list[str] | None = None,
    name: str | None = None,
    area: str | None = None,
    floor: str | None = None,
) -> list[str]:
    """Resolve intent-based targeting (area/name/floor/domain/device_class) to entity_id list.

    Silently drops entities the token cannot WRITE. Never acknowledges blocked or
    inaccessible entities. Returns an empty list when nothing matches.
    """
    er_inst = er.async_get(hass)
    ar_inst = ar.async_get(hass)
    dr_inst = dr.async_get(hass)

    states = list(hass.states.async_all())

    if domains:
        domain_set = set(domains)
        states = [s for s in states if s.entity_id.split(".")[0] in domain_set]

    if device_classes:
        dc_set = set(device_classes)
        states = [s for s in states if s.attributes.get("device_class") in dc_set]

    if floor:
        floor_lower = floor.lower()
        floor_area_ids: set[str] = set()
        for a in ar_inst.async_list_areas():
            fid = getattr(a, "floor_id", None)
            if fid and fid.lower() == floor_lower:
                floor_area_ids.add(a.id)
        if not floor_area_ids:
            return []
        floor_entity_ids: set[str] = set()
        for entry in er_inst.entities.values():
            if entry.disabled_by:
                continue
            if entry.area_id in floor_area_ids:
                floor_entity_ids.add(entry.entity_id)
            elif entry.device_id:
                device = dr_inst.async_get(entry.device_id)
                if device and device.area_id in floor_area_ids:
                    floor_entity_ids.add(entry.entity_id)
        states = [s for s in states if s.entity_id in floor_entity_ids]

    if area:
        area_lower = area.lower()
        target_area = None
        for a in ar_inst.async_list_areas():
            if a.id == area or a.name.lower() == area_lower:
                target_area = a
                break
        if target_area is None:
            return []
        area_entity_ids: set[str] = set()
        for entry in er_inst.entities.values():
            if entry.disabled_by:
                continue
            if entry.area_id == target_area.id:
                area_entity_ids.add(entry.entity_id)
            elif entry.device_id:
                device = dr_inst.async_get(entry.device_id)
                if device and device.area_id == target_area.id:
                    area_entity_ids.add(entry.entity_id)
        states = [s for s in states if s.entity_id in area_entity_ids]

    if name:
        name_lower = name.lower()
        states = [
            s for s in states
            if name_lower in s.attributes.get("friendly_name", "").lower()
        ]

    result: list[str] = []
    for s in states:
        eid = s.entity_id
        if eid.split(".")[0] in BLOCKED_DOMAINS:
            continue
        if token.pass_through:
            result.append(eid)
        elif resolve(eid, token, hass) == Permission.WRITE:
            result.append(eid)

    return result

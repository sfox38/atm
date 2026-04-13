"""Token storage CRUD for ATM. No business logic lives here."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
from homeassistant.helpers.storage import Store
from homeassistant.util.dt import parse_datetime, utcnow

from .const import (
    DEFAULT_RATE_LIMIT_BURST,
    DEFAULT_RATE_LIMIT_REQUESTS,
    STORAGE_KEY,
    STORAGE_VERSION,
    TOKEN_HEX_LENGTH,
    TOKEN_PREFIX,
)


_VALID_NODE_STATES = frozenset({"GREY", "YELLOW", "GREEN", "RED"})


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return parse_datetime(value)


@dataclass
class PermissionNode:
    """Permission state for one node in the hierarchy (domain, device, or entity).

    state is one of GREY (inherit), YELLOW (read), GREEN (write), RED (deny).
    hint is an optional human-readable label used in the context endpoint.
    """

    state: str = "GREY"
    hint: str | None = None

    def to_dict(self) -> dict:
        return {"state": self.state, "hint": self.hint}

    @classmethod
    def from_dict(cls, data: dict) -> PermissionNode:
        state = data.get("state", "GREY")
        if state not in _VALID_NODE_STATES:
            raise ValueError(f"Invalid permission node state: {state!r}")
        return cls(state=state, hint=data.get("hint"))


@dataclass
class PermissionTree:
    """Three-level permission hierarchy: domains, devices, and entities.

    Each level is a dict keyed by the relevant ID. Nodes with state GREY are
    omitted from storage; their absence implies inheritance.
    """

    domains: dict[str, PermissionNode] = field(default_factory=dict)
    devices: dict[str, PermissionNode] = field(default_factory=dict)
    entities: dict[str, PermissionNode] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "domains": {k: v.to_dict() for k, v in self.domains.items()},
            "devices": {k: v.to_dict() for k, v in self.devices.items()},
            "entities": {k: v.to_dict() for k, v in self.entities.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> PermissionTree:
        return cls(
            domains={k: PermissionNode.from_dict(v) for k, v in data.get("domains", {}).items()},
            devices={k: PermissionNode.from_dict(v) for k, v in data.get("devices", {}).items()},
            entities={k: PermissionNode.from_dict(v) for k, v in data.get("entities", {}).items()},
        )


@dataclass
class TokenRecord:
    """Active ATM token with its configuration and permission tree."""

    id: str
    name: str
    token_hash: str
    created_at: datetime
    created_by: str
    expires_at: datetime | None = None
    revoked: bool = False
    last_used_at: datetime | None = None
    pass_through: bool = False
    rate_limit_requests: int = DEFAULT_RATE_LIMIT_REQUESTS
    rate_limit_burst: int = DEFAULT_RATE_LIMIT_BURST
    allow_automation_write: bool = False
    allow_config_read: bool = False
    allow_template_render: bool = False
    allow_restart: bool = False
    permissions: PermissionTree = field(default_factory=PermissionTree)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "token_hash": self.token_hash,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revoked": self.revoked,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "pass_through": self.pass_through,
            "rate_limit_requests": self.rate_limit_requests,
            "rate_limit_burst": self.rate_limit_burst,
            "allow_automation_write": self.allow_automation_write,
            "allow_config_read": self.allow_config_read,
            "allow_template_render": self.allow_template_render,
            "allow_restart": self.allow_restart,
            "permissions": self.permissions.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> TokenRecord:
        return cls(
            id=data["id"],
            name=data["name"],
            token_hash=data["token_hash"],
            created_at=_parse_dt(data["created_at"]),
            created_by=data["created_by"],
            expires_at=_parse_dt(data.get("expires_at")),
            revoked=data.get("revoked", False),
            last_used_at=_parse_dt(data.get("last_used_at")),
            pass_through=data.get("pass_through", False),
            rate_limit_requests=data.get("rate_limit_requests", DEFAULT_RATE_LIMIT_REQUESTS),
            rate_limit_burst=data.get("rate_limit_burst", DEFAULT_RATE_LIMIT_BURST),
            allow_automation_write=data.get("allow_automation_write", False),
            allow_config_read=data.get("allow_config_read", False),
            allow_template_render=data.get("allow_template_render", False),
            allow_restart=data.get("allow_restart", False),
            permissions=PermissionTree.from_dict(data.get("permissions", {})),
        )

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return utcnow() >= self.expires_at

    def is_valid(self) -> bool:
        return not self.revoked and not self.is_expired()


@dataclass
class ArchivedTokenRecord:
    """Archived snapshot of a revoked or expired token. Retained for audit purposes."""

    id: str
    name: str
    token_hash: str
    created_at: datetime
    created_by: str
    revoked_at: datetime
    revoked: bool = False
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    pass_through: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "token_hash": self.token_hash,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "revoked_at": self.revoked_at.isoformat(),
            "revoked": self.revoked,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "pass_through": self.pass_through,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ArchivedTokenRecord:
        return cls(
            id=data["id"],
            name=data["name"],
            token_hash=data["token_hash"],
            created_at=_parse_dt(data["created_at"]),
            created_by=data["created_by"],
            revoked_at=_parse_dt(data["revoked_at"]),
            revoked=data.get("revoked", False),
            expires_at=_parse_dt(data.get("expires_at")),
            last_used_at=_parse_dt(data.get("last_used_at")),
            pass_through=data.get("pass_through", False),
        )


@dataclass
class GlobalSettings:
    """Integration-wide settings persisted to storage."""

    kill_switch: bool = False
    disable_all_logging: bool = False
    log_allowed: bool = True
    log_denied: bool = True
    log_rate_limited: bool = True
    log_entity_names: bool = True
    log_client_ip: bool = True
    notify_on_rate_limit: bool = False
    audit_flush_interval: int = 15
    audit_log_maxlen: int = 10000

    def to_dict(self) -> dict:
        return {
            "kill_switch": self.kill_switch,
            "disable_all_logging": self.disable_all_logging,
            "log_allowed": self.log_allowed,
            "log_denied": self.log_denied,
            "log_rate_limited": self.log_rate_limited,
            "log_entity_names": self.log_entity_names,
            "log_client_ip": self.log_client_ip,
            "notify_on_rate_limit": self.notify_on_rate_limit,
            "audit_flush_interval": self.audit_flush_interval,
            "audit_log_maxlen": self.audit_log_maxlen,
        }

    @classmethod
    def from_dict(cls, data: dict) -> GlobalSettings:
        return cls(
            kill_switch=data.get("kill_switch", False),
            disable_all_logging=data.get("disable_all_logging", False),
            log_allowed=data.get("log_allowed", True),
            log_denied=data.get("log_denied", True),
            log_rate_limited=data.get("log_rate_limited", True),
            log_entity_names=data.get("log_entity_names", True),
            log_client_ip=data.get("log_client_ip", True),
            notify_on_rate_limit=data.get("notify_on_rate_limit", False),
            audit_flush_interval=data.get("audit_flush_interval", 15),
            audit_log_maxlen=data.get("audit_log_maxlen", 10000),
        )


class TokenStore:
    """Manages persistent storage and in-memory state for ATM tokens."""

    def __init__(self, hass: HomeAssistant, store: Store) -> None:
        self._hass = hass
        self._store = store
        self._tokens: dict[str, TokenRecord] = {}
        self._archived: dict[str, ArchivedTokenRecord] = {}
        self._settings: GlobalSettings = GlobalSettings()
        self.async_lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    async def async_create(cls, hass: HomeAssistant) -> TokenStore:
        """Create a TokenStore and load persisted data from HA storage."""
        store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        instance = cls(hass, store)
        await instance.async_load()
        return instance

    async def async_load(self) -> None:
        """Load token and settings data from the HA storage file."""
        raw = await self._store.async_load() or {}
        tokens: dict[str, TokenRecord] = {}
        for r in raw.get("tokens", []):
            try:
                record = TokenRecord.from_dict(r)
                tokens[record.id] = record
            except (KeyError, TypeError, ValueError) as exc:
                _LOGGER.warning("Skipping corrupt token record %r: %s", r.get("id", "?"), exc)
        self._tokens = tokens

        archived: dict[str, ArchivedTokenRecord] = {}
        for r in raw.get("archived_tokens", []):
            try:
                record = ArchivedTokenRecord.from_dict(r)
                archived[record.id] = record
            except (KeyError, TypeError, ValueError) as exc:
                _LOGGER.warning("Skipping corrupt archived token record %r: %s", r.get("id", "?"), exc)
        self._archived = archived

        self._settings = GlobalSettings.from_dict(raw.get("settings", {}))

    async def async_save(self) -> None:
        """Persist the current in-memory state to HA storage."""
        await self._store.async_save({
            "version": STORAGE_VERSION,
            "tokens": [t.to_dict() for t in self._tokens.values()],
            "archived_tokens": [a.to_dict() for a in self._archived.values()],
            "settings": self._settings.to_dict(),
        })

    async def async_create_token(
        self,
        name: str,
        created_by: str,
        expires_at: datetime | None = None,
        pass_through: bool = False,
        rate_limit_requests: int = DEFAULT_RATE_LIMIT_REQUESTS,
        rate_limit_burst: int = DEFAULT_RATE_LIMIT_BURST,
    ) -> tuple[TokenRecord, str]:
        """Generate a new token, store it, and return (record, raw_token).

        The raw_token value is returned exactly once and never stored. Callers
        must pass it to the client immediately and discard it.
        """
        raw_token = TOKEN_PREFIX + secrets.token_hex(TOKEN_HEX_LENGTH // 2)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        record = TokenRecord(
            id=str(uuid.uuid4()),
            name=name,
            token_hash=token_hash,
            created_at=utcnow(),
            created_by=created_by,
            expires_at=expires_at,
            pass_through=pass_through,
            rate_limit_requests=rate_limit_requests,
            rate_limit_burst=rate_limit_burst if rate_limit_requests > 0 else 0,
        )
        self._tokens[record.id] = record
        await self.async_save()
        return record, raw_token

    def get_token_by_id(self, token_id: str) -> TokenRecord | None:
        return self._tokens.get(token_id)

    def get_token_by_hash(self, token_hash: str) -> TokenRecord | None:
        """Find a token by constant-time comparison of SHA-256 hashes."""
        for token in self._tokens.values():
            if hmac_compare(token.token_hash, token_hash):
                return token
        return None

    def get_archived_by_hash(self, token_hash: str) -> ArchivedTokenRecord | None:
        for record in self._archived.values():
            if hmac_compare(record.token_hash, token_hash):
                return record
        return None

    def list_tokens(self) -> list[TokenRecord]:
        return list(self._tokens.values())

    def list_archived(self) -> list[ArchivedTokenRecord]:
        return list(self._archived.values())

    def active_token_count(self) -> int:
        return len(self._tokens)

    def name_slug_exists(self, name: str) -> bool:
        """Return True if a token with an equivalent slug already exists."""
        slug = token_name_slug(name)
        return any(token_name_slug(t.name) == slug for t in self._tokens.values())

    async def async_archive_token(
        self,
        token_id: str,
        revoked: bool,
        revoked_at: datetime | None = None,
    ) -> ArchivedTokenRecord | None:
        """Move a token from the active list to the archive and persist.

        Returns None if the token_id is not found.
        """
        token = self._tokens.pop(token_id, None)
        if token is None:
            return None
        token.revoked = True
        archived = ArchivedTokenRecord(
            id=token.id,
            name=token.name,
            token_hash=token.token_hash,
            created_at=token.created_at,
            created_by=token.created_by,
            revoked_at=revoked_at or utcnow(),
            revoked=revoked,
            expires_at=token.expires_at,
            last_used_at=token.last_used_at,
            pass_through=token.pass_through,
        )
        self._archived[archived.id] = archived
        await self.async_save()
        return archived

    async def async_patch_token(
        self,
        token_id: str,
        **kwargs,
    ) -> TokenRecord | None:
        """Update mutable capability and rate-limit fields on a token and persist.

        When rate_limit_requests is set to 0, rate_limit_burst is forced to 0.
        Returns None if the token is not found.
        """
        token = self._tokens.get(token_id)
        if token is None:
            return None
        mutable_fields = {
            "pass_through",
            "rate_limit_requests",
            "rate_limit_burst",
            "allow_automation_write",
            "allow_config_read",
            "allow_template_render",
            "allow_restart",
        }
        for key, value in kwargs.items():
            if key in mutable_fields:
                setattr(token, key, value)
        if token.rate_limit_requests == 0:
            token.rate_limit_burst = 0
        await self.async_save()
        return token

    async def async_set_permissions(
        self,
        token_id: str,
        permissions: PermissionTree,
    ) -> TokenRecord | None:
        """Replace the entire permission tree for a token and persist."""
        token = self._tokens.get(token_id)
        if token is None:
            return None
        token.permissions = permissions
        await self.async_save()
        return token

    async def async_patch_permission_node(
        self,
        token_id: str,
        node_type: str,
        node_id: str,
        state: str,
        hint: str | None = None,
    ) -> TokenRecord | None:
        """Set or clear a single permission node and persist.

        Setting state to GREY removes the node entirely (GREY is the default
        and is not stored explicitly).
        """
        token = self._tokens.get(token_id)
        if token is None:
            return None
        collection = getattr(token.permissions, node_type, None)
        if collection is None:
            return None
        if state == "GREY":
            collection.pop(node_id, None)
        else:
            collection[node_id] = PermissionNode(state=state, hint=hint)
        await self.async_save()
        return token

    def update_last_used(self, token_id: str, timestamp: datetime) -> None:
        """Record a last-used timestamp in memory only.

        Flushed periodically to storage by the interval registered in __init__.py
        and immediately on HA shutdown.
        """
        token = self._tokens.get(token_id)
        if token is not None:
            token.last_used_at = timestamp

    async def async_flush_last_used(self) -> None:
        """Flush in-memory last_used_at timestamps to storage."""
        await self.async_save()

    async def async_delete_archived(self, token_id: str) -> bool:
        """Permanently delete an archived token record. Returns False if not found."""
        async with self.async_lock:
            if token_id not in self._archived:
                return False
            del self._archived[token_id]
            await self.async_save()
        return True

    def get_settings(self) -> GlobalSettings:
        return self._settings

    async def async_patch_settings(self, **kwargs) -> GlobalSettings:
        """Update any GlobalSettings fields by name and persist."""
        for key, value in kwargs.items():
            if hasattr(self._settings, key):
                setattr(self._settings, key, value)
        await self.async_save()
        return self._settings

    async def async_wipe(self) -> None:
        """Clear all tokens, archived records, and settings, then persist."""
        self._tokens.clear()
        self._archived.clear()
        self._settings = GlobalSettings()
        await self.async_save()


def token_name_slug(name: str) -> str:
    """Normalize a token name to a slug (lowercase, hyphens to underscores)."""
    return name.lower().replace("-", "_")


def hmac_compare(stored_hash: str, presented_hash: str) -> bool:
    """Constant-time comparison of two SHA-256 hex digests."""
    return hmac.compare_digest(stored_hash, presented_hash)

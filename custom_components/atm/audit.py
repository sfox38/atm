"""In-memory circular buffer audit log for ATM. No I/O."""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from homeassistant.util.dt import utcnow

from .const import AUDIT_LOG_MAXLEN
from .token_store import GlobalSettings

Outcome = Literal["allowed", "denied", "not_found", "rate_limited"]

_REDACTED = "[redacted]"

MAX_QUERY_LIMIT = 500


def generate_request_id() -> str:
    """Return a new UUID string for use as X-ATM-Request-ID."""
    return str(uuid.uuid4())


@dataclass
class AuditEntry:
    request_id: str
    timestamp: datetime
    token_id: str
    token_name: str
    method: str
    resource: str
    outcome: Outcome
    client_ip: str
    pass_through: bool = False

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat(),
            "token_id": self.token_id,
            "token_name": self.token_name,
            "method": self.method,
            "resource": self.resource,
            "outcome": self.outcome,
            "client_ip": self.client_ip,
            "pass_through": self.pass_through,
        }


class AuditLog:
    """Circular buffer audit log.

    State is in-memory only and is lost on HA restart. The maxlen parameter
    exists for testability; production code always uses the default.

    Logging toggles from GlobalSettings are evaluated at record time, not at
    query time. Sensor counters in sensor.py are updated independently of
    these toggles and always reflect total activity.
    """

    def __init__(self, maxlen: int = AUDIT_LOG_MAXLEN) -> None:
        self._log: deque[AuditEntry] = deque(maxlen=maxlen)

    def record(
        self,
        *,
        request_id: str,
        token_id: str,
        token_name: str,
        method: str,
        resource: str,
        outcome: Outcome,
        client_ip: str,
        settings: GlobalSettings,
        pass_through: bool = False,
        timestamp: datetime | None = None,
    ) -> None:
        """Append an audit entry, subject to the current logging settings.

        Returns without writing if the master kill switch or the relevant
        per-outcome toggle is off. Redaction of resource and client_ip is
        applied when the corresponding setting is off.
        """
        if settings.disable_all_logging:
            return

        if outcome == "allowed" and not settings.log_allowed:
            return
        if outcome in ("denied", "not_found") and not settings.log_denied:
            return
        if outcome == "rate_limited" and not settings.log_rate_limited:
            return

        logged_resource = resource if settings.log_entity_names else _REDACTED
        logged_ip = client_ip if settings.log_client_ip else _REDACTED

        self._log.append(AuditEntry(
            request_id=request_id,
            timestamp=timestamp or utcnow(),
            token_id=token_id,
            token_name=token_name,
            method=method,
            resource=logged_resource,
            outcome=outcome,
            client_ip=logged_ip,
            pass_through=pass_through,
        ))

    def query(
        self,
        *,
        token_id: str | None = None,
        outcome: str | None = None,
        client_ip: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEntry]:
        """Return filtered, paginated audit entries in reverse-chronological order.

        limit is capped at MAX_QUERY_LIMIT (500). offset is applied after filtering.
        """
        limit = min(limit, MAX_QUERY_LIMIT)

        entries = list(self._log)

        if token_id is not None:
            entries = [e for e in entries if e.token_id == token_id]
        if outcome is not None:
            entries = [e for e in entries if e.outcome == outcome]
        if client_ip is not None:
            entries = [e for e in entries if e.client_ip == client_ip]

        entries.reverse()
        return entries[offset:offset + limit]

    def clear(self) -> None:
        """Remove all entries. Called on wipe action."""
        self._log.clear()

    def __len__(self) -> int:
        return len(self._log)

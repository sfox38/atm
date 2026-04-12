"""Constants for the Advanced Token Management (ATM) integration."""

import datetime
import re

ATM_VERSION = "1.0.0"
DOMAIN = "atm"
STORAGE_KEY = "atm"
STORAGE_VERSION = 1

PROXY_TIMEOUT_SECONDS = 30
MAX_REQUEST_BODY_BYTES = 1_048_576
MAX_ACTIVE_TOKENS_WARNING = 50
MAX_SSE_CONNECTIONS_PER_TOKEN = 5

TOKEN_PREFIX = "atm_"
TOKEN_HEX_LENGTH = 64
TOKEN_LENGTH = len(TOKEN_PREFIX) + TOKEN_HEX_LENGTH

TOKEN_NAME_REGEX = re.compile(r"^[A-Za-z0-9_\-]{3,32}$")

DEFAULT_RATE_LIMIT_REQUESTS = 60
DEFAULT_RATE_LIMIT_BURST = 10

SSE_HEARTBEAT_INTERVAL = datetime.timedelta(seconds=15)
FLUSH_INTERVAL = datetime.timedelta(minutes=5)
EXPIRY_CHECK_INTERVAL = datetime.timedelta(minutes=1)

AUDIT_LOG_MAXLEN = 10000
AUDIT_STORAGE_KEY = "atm_audit"
AUDIT_STORAGE_VERSION = 1
AUDIT_FLUSH_INTERVAL_DEFAULT = 15  # minutes; 0 = never

SENSITIVE_ATTRIBUTES = frozenset({
    "entity_picture",
    "stream_url",
    "access_token",
    "still_image_url",
})

BLOCKED_DOMAINS = frozenset({"atm"})

DUAL_GATE_SERVICES = frozenset({
    "homeassistant/restart",
    "homeassistant/stop",
})


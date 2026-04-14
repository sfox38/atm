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
SENSOR_PUSH_INTERVAL = datetime.timedelta(hours=1)

AUDIT_LOG_MAXLEN = 10000
AUDIT_STORAGE_KEY = "atm_audit"
AUDIT_STORAGE_VERSION = 1
# audit_flush_interval is stored and exposed in minutes (not seconds).
# Valid values: 0 (disable periodic flush), 5, 10, 15, 30, 60.

SENSITIVE_ATTRIBUTES = frozenset({
    "entity_picture",
    "stream_url",
    "access_token",
    "still_image_url",
})

BLOCKED_DOMAINS = frozenset({"atm"})

HIGH_RISK_DOMAINS = frozenset({
    "homeassistant",
    "recorder",
    "system_log",
    "hassio",
    "backup",
    "notify",
    "persistent_notification",
    "mqtt",
})

DUAL_GATE_SERVICES = frozenset({
    "homeassistant/restart",
    "homeassistant/stop",
})

# Services that require allow_physical_control even when pass_through is True.
# These represent irreversible or safety-relevant physical actions.
PHYSICAL_GATE_SERVICES = frozenset({
    "lock/lock",
    "lock/unlock",
    "alarm_control_panel/alarm_disarm",
    "alarm_control_panel/alarm_arm_away",
    "alarm_control_panel/alarm_arm_home",
    "alarm_control_panel/alarm_arm_night",
    "alarm_control_panel/alarm_arm_vacation",
    "alarm_control_panel/alarm_trigger",
    "cover/open_cover",
    "cover/stop_cover",
    "cover/set_cover_position",
    "cover/set_cover_tilt_position",
})

# assist_satellite feature bit for ANNOUNCE support.
ANNOUNCE_BIT = 2

# Maximum time range for history and statistics queries.
MAX_HISTORY_RANGE_DAYS = 7

# Maximum number of log entries returned by the logs endpoint/tool.
MAX_LOG_ENTRIES = 100


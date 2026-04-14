# Advanced Token Management (ATM)

Home Assistant's built-in Long-Lived Access Tokens (LLATs) give the holder broad access to your HA instance. While HA's native MCP server does allow you to control which entities are exposed to voice assistants and MCP clients via **Settings > Voice Assistants > Expose**, that control is coarse: it is binary (exposed or not), it applies to all MCP clients equally, and the underlying LLAT still carries full administrative access to HA itself.

ATM replaces that model with per-token, per-entity access control. Each ATM token carries its own permission rules, rate limit, optional expiry, and a full audit trail. An AI assistant can be given read-only access to your sensors and write access to your lights, while your locks, alarms, cameras, and admin functions remain completely invisible to it. A home automation script can have different access than Claude Code. If a token is compromised, you revoke it in one click and all open connections are terminated immediately.

ATM exposes a REST proxy and an MCP endpoint, both running inside Home Assistant's own web server. No separate process, no outbound connections, no cloud dependency.

---

## Why ATM instead of a LLAT

| | LLAT + native MCP | ATM token |
|---|---|---|
| Entity filtering | Binary expose/hide, same for all clients | Four permission states, per token |
| Per-client control | No - all clients see the same exposed entities | Yes - each token has independent permissions |
| Read-only access | No | Yes - YELLOW state allows reads, blocks writes |
| Audit trail | None | Every request logged with outcome and entity |
| Rate limiting | None | Per-token, configurable |
| Expiry | None | Optional, auto-archived on expiry |
| Revocation | Revoke LLAT via HA profile page | Instant, terminates open connections immediately |
| Sensitive attribute scrubbing | None | Always applied |
| MCP endpoint | Built into HA | Built into ATM, with scoped access |

If you are connecting Claude Code, Cursor, ChatGPT, or any other AI tool to your Home Assistant, ATM gives you control that the native system cannot provide.

---

## Requirements

- Home Assistant 2024.1 or later
- Python 3.11 or later (bundled with HA)
- No additional Python packages required

---

## Installation

### Via HACS

1. In HACS, go to **Integrations** and click the menu in the top-right corner.
2. Choose **Custom repositories**.
3. Enter `https://github.com/sfox38/atm` and select **Integration** as the category.
4. Click **Add**, then find ATM in the HACS integration list and install it.
5. Restart Home Assistant.

### Manual

1. Copy the `custom_components/atm` folder into your HA config directory under `custom_components/atm`.
2. Restart Home Assistant.

### Setup

After installation, go to **Settings > Devices and services > Add integration** and search for "Advanced Token Management". Click through the single-step config flow. Only one ATM instance can be configured at a time.

> [!NOTE]
> Once installed, use the **ATM** panel in your Home Assistant sidebar to manage your tokens.

---

## Connecting Claude Code via MCP

ATM exposes an MCP endpoint at `/api/atm/mcp`. This is the recommended way to connect Claude Code to your Home Assistant instance.

### Step 1: Create a token

In the ATM sidebar panel, click **Create Token**. Give it a name like `claude-code`. Configure the permission tree to grant access to the domains and entities you want Claude to work with. Enable `allow_template_render` if you want Claude to render Jinja templates.

Copy the raw token value when it is displayed. It is shown exactly once and cannot be retrieved again.

### Step 2: Add the MCP server to Claude Code

Run this command in your terminal, replacing the URL with your HA address and the token with what you copied:

```bash
claude mcp add --transport http home-assistant \
  http://your-ha-address:8123/api/atm/mcp \
  --header "Authorization: Bearer atm_your_token_here"
```

If you use Nabu Casa remote access or a custom domain:

```bash
claude mcp add --transport http home-assistant \
  https://your-instance.ui.nabu.casa/api/atm/mcp \
  --header "Authorization: Bearer atm_your_token_here"
```

### Step 3: Verify

Start a new Claude Code session and run `/mcp`. The `home-assistant` server should show as connected. Ask Claude to list your entities or check a light state to confirm it is working.

### Available MCP tools

ATM is a drop-in replacement for the native HA MCP server. It exposes all 20 native HA MCP tools plus ATM-specific tools for direct entity access and system operations.

**Native HA MCP tools** - functionally identical to the native HA MCP server, scoped to the token's permission tree:

| Tool | Description |
|---|---|
| `GetLiveContext` | YAML snapshot of accessible entity states |
| `GetDateTime` | Current date, time, and timezone |
| `HassTurnOn` / `HassTurnOff` | Turn devices on or off by area, name, floor, or domain |
| `HassLightSet` | Set light brightness, color, or color temperature |
| `HassFanSetSpeed` | Set fan speed |
| `HassClimateSetTemperature` | Set climate device target temperature |
| `HassSetPosition` | Set position of covers or similar devices |
| `HassSetVolume` / `HassSetVolumeRelative` | Set or adjust media player volume |
| `HassMediaPause` / `HassMediaUnpause` | Pause or resume media playback |
| `HassMediaNext` / `HassMediaPrevious` | Skip tracks on a media player |
| `HassMediaSearchAndPlay` | Search and play media |
| `HassMediaPlayerMute` / `HassMediaPlayerUnmute` | Mute or unmute a media player |
| `HassCancelAllTimers` | Cancel all timers in an area |
| `HassStopMoving` | Stop a moving cover or device |

**ATM entity tools** - direct entity access filtered by permission tree:

| Tool | Requires flag |
|---|---|
| `get_state` - current state of one entity | none |
| `get_states` - all accessible entity states | none |
| `get_history` - state history (supports `24h`, `7d`, `2w`, `1m`) | none |
| `get_statistics` - long-term statistics for numeric entities | none |
| `call_service` - call a HA service by domain and service name | none |

**System tools** - gated by capability flags:

| Tool | Requires flag |
|---|---|
| `render_template` - render a Jinja2 template | `allow_template_render` |
| `get_config` - HA configuration info | `allow_config_read` |
| `restart_ha` - restart Home Assistant | `allow_restart` |
| `HassBroadcast` - announce a message via assist satellite devices | `allow_broadcast` |
| `create_automation` - create a new automation in `automations.yaml` | `allow_automation_write` |
| `edit_automation` - replace an existing automation's configuration | `allow_automation_write` |
| `delete_automation` - permanently delete an automation | `allow_automation_write` |
| `create_script` - create a new script in `scripts.yaml` | `allow_script_write` |
| `edit_script` - replace an existing script's configuration | `allow_script_write` |
| `delete_script` - permanently delete a script | `allow_script_write` |

Claude can only see and act on entities within the token's permission scope. Native tools silently skip inaccessible entities without revealing they exist.

> [!NOTE]
> After enabling or disabling a capability flag in the ATM panel, your MCP client must reconnect to receive the updated tool list. In Claude Code, use the `/mcp` menu and select **Reconnect**.

---

## Using Third-Party MCP Servers

If you use a third-party MCP server for Home Assistant such as ha-mcp, you can point it at ATM using a pass-through token instead of your LLAT. You get the same full entity access but with rate limiting, audit logging, revocation, and sensitive attribute scrubbing applied automatically.

> [!NOTE]
> See [EXTERNAL_MCP_SERVERS.md](EXTERNAL_MCP_SERVERS.md) for setup instructions for specific third-party servers.

---

## The Permission System

Every token has a permission tree organized into three levels: domains, devices, and entities. Each node carries one of four states.

### The four states

⬜ **GREY** - no opinion, inherit from parent. A ⬜ GREY entity under a 🟢 GREEN domain gets the domain's permission. ⬜ GREY at every level means no access.

🟡 **YELLOW** - read-only. The token can read the current state. It cannot call services that change state.

🟢 **GREEN** - read and write. The token can read state and call services.

🔴 **RED** - explicit deny. Blocks this node and everything beneath it. 🔴 RED cannot be overridden by any child node. It is a hard stop.

### How a permission is resolved

When a request arrives for an entity, ATM runs two checks:

**Pass 1 - 🔴 RED scan.** ATM walks the ancestor chain: entity, then device, then domain. If any node is 🔴 RED, the request is denied immediately. No other node matters.

**Pass 2 - most specific grant.** ATM walks the same chain looking for the most specific non-⬜ GREY node. That color becomes the effective permission. If no non-⬜ GREY node exists, the result is NO_ACCESS, which is indistinguishable from DENY to the caller.

### Examples

**Token with no grants.** All ⬜ GREY. The token can see and do nothing. This is the safe default. Add grants incrementally.

**Read all lights, control the living room.**
- Set the `light` domain to 🟡 YELLOW.
- Set `light.living_room` to 🟢 GREEN.

The token can read any light state. It can only call turn_on/turn_off on `light.living_room`.

**Full access to lights except the guest bedroom.**
- Set the `light` domain to 🟢 GREEN.
- Set the guest bedroom device to 🔴 RED.

All lights are writable. Every entity on the guest bedroom device is denied, even though the domain is 🟢 GREEN. 🔴 RED wins.

**Block one diagnostic sensor inside a permitted device.**
- Set the device to 🟢 GREEN.
- Set the specific diagnostic entity to 🔴 RED.

All entities on the device are writable except that one sensor, which is completely inaccessible.

### What ATM always blocks

These apply to every token including pass-through and are not configurable:

- The `atm` domain (all internal ATM sensors) is permanently blocked and invisible.
- Entity attributes that could expose security credentials (`access_token`, `entity_picture`, `stream_url`, `still_image_url`) are stripped from every state response.

---

## Capability Flags

Some operations require explicit opt-in even for tokens with 🟢 GREEN domain access:

| Flag | What it enables | Pass-through exempt |
|---|---|---|
| `allow_restart` | `homeassistant.restart` and `homeassistant.stop` | yes |
| `allow_physical_control` | Lock, alarm, and cover mutation services (e.g. `lock.unlock`, `alarm_control_panel.alarm_disarm`, `cover.open_cover`) | yes |
| `allow_automation_write` | Creating, editing, and deleting automations via the MCP tools. See security note below. | yes |
| `allow_script_write` | Creating, editing, and deleting scripts via the MCP tools. See security note below. | yes |
| `allow_config_read` | Reading HA configuration data and the event bus listener list | no |
| `allow_template_render` | Rendering Jinja2 templates (permission-scoped environment) | no |
| `allow_service_response` | Return response data from services that support it (e.g. `conversation.process`). Silently omitted for services that do not declare a response schema. | no |
| `allow_broadcast` | Sending announcements via the `HassBroadcast` MCP tool through assist satellite devices. | no |

The four pass-through-exempt flags (`allow_restart`, `allow_physical_control`, `allow_automation_write`, `allow_script_write`) must be explicitly enabled even for pass-through tokens. All other flags are bypassed by pass-through tokens.

### Automation and script write flags

`allow_automation_write` and `allow_script_write` are elevated-trust capabilities. Enable them only for tokens held by clients you fully control.

**These flags are all-or-nothing.** The automation and script write tools (`create_automation`, `edit_automation`, `delete_automation`, `create_script`, `edit_script`, `delete_script`) write directly to `automations.yaml` and `scripts.yaml`. They do not consult the token's entity permission tree. A client with `allow_automation_write` enabled can write an automation referencing any entity in Home Assistant, regardless of what the token is permitted to access directly via `get_state` or `call_service`.

**The entity permission tree cannot restrict automation/script write.** Setting the `automation` or `script` domain to READ or DENY in the permission tree has no effect on these MCP tools. A DENY on `automation.*` only blocks entity-scoped operations (reading automation entity state, calling `automation.trigger`). It does not prevent the write tools from creating or modifying automation YAML.

**Triggered actions run outside ATM.** An automation or script created through ATM is subsequently triggered by HA's own automation engine, which runs under HA's own context - not ATM's. Permission checks do not apply to the actions taken when a triggered automation runs.

In practice, a token with a narrow entity scope but `allow_automation_write` enabled could - through a crafted automation - indirectly control entities it cannot access directly. Only enable these flags for clients you would trust with broad HA access.

---

## Pass-Through Mode

Pass-through tokens bypass the three-level permission check and have 🟢 GREEN access to all entities. They are intended for trusted tools where managing a full permission tree is impractical, or for routing a third-party MCP server through ATM.

Pass-through does NOT bypass:
- The `atm` domain blocklist
- Sensitive attribute scrubbing
- Rate limiting
- `allow_restart` - a pass-through token cannot call `homeassistant.restart` or `homeassistant.stop` without this flag explicitly enabled.
- `allow_physical_control` - a pass-through token cannot call lock, alarm, or cover mutation services without this flag explicitly enabled.
- `allow_automation_write` - a pass-through token cannot create, edit, or delete automations without this flag explicitly enabled.
- `allow_script_write` - a pass-through token cannot create, edit, or delete scripts without this flag explicitly enabled.

These four flags must always be explicitly enabled, regardless of pass-through mode. All other capability flags (`allow_config_read`, `allow_template_render`, `allow_service_response`, `allow_broadcast`) are bypassed by pass-through tokens.

The ATM panel shows a confirmation dialog before enabling pass-through on a token. When using the admin API directly, the PATCH request must include `"confirm_pass_through": true` alongside `"pass_through": true` - this is a required acknowledgment field that prevents accidentally enabling pass-through. Omitting it returns a 400 error. Use pass-through only for tools you fully control. For anything externally hosted or shared, use a scoped permission tree instead.

---

## Rate Limiting

Every token has a sliding window rate limit. The defaults are 60 requests per minute with a burst allowance of 10 per second. Both are configurable per token. Setting `rate_limit_requests` to 0 disables rate limiting entirely for that token.

When a request is rate limited, ATM returns HTTP 429 with a `Retry-After` header. Successful responses include rate limit headers:

```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 47
X-RateLimit-Reset: 1712345678
```

If `notify_on_rate_limit` is enabled in global settings, HA creates a persistent notification when a token hits its limit. This is throttled to once per token per minute.

---

## Security

### Token design

- Tokens are 68 characters with a fixed `atm_` prefix. Any value that does not match this exact format is rejected before any storage lookup.
- Only the SHA-256 hash of the token is stored. The raw value is never written to disk or logs.
- Token comparisons always use a constant-time algorithm (`hmac.compare_digest`). String equality (`==`) is never used for token validation.
- Tokens are only accepted in the `Authorization: Bearer` header. Query parameters are rejected with 401. No token value ever appears in HA logs.

### Permission enforcement

- Every request is validated against the full two-pass permission algorithm. No endpoint implements its own shortcut.
- Entity not found and entity inaccessible return identical response bodies. A caller cannot determine whether an entity exists or is simply blocked.
- Sensitive attributes are stripped from every state response, for every token type.
- Service calls that include `device_id` or `area_id` are always expanded to an explicit entity list before being passed to HA. Denied entities are silently excluded.
- If all entities in a service call resolve to denied, ATM returns 403 rather than calling HA with an empty list.
- Service response data is scanned for entity IDs. Any entity ID the token cannot access is replaced with `"<redacted>"`.
- If an entity ID in a service call does not exist in the HA entity registry, ATM returns 403. Entity creation via service calls is not permitted.
- Physical control services (`lock.unlock`, `alarm_control_panel.alarm_disarm`, `cover.open_cover`, and related services) require `allow_physical_control` in addition to entity-level WRITE permission. This applies even to pass-through tokens.
- Automation and script write MCP tools bypass the entity permission tree. Setting the `automation` or `script` domain to RED or YELLOW does not prevent these tools from writing YAML. See the [Automation and script write flags](#automation-and-script-write-flags) section.

### Token lifecycle

When a token is revoked, ATM immediately archives it to storage, terminates all open SSE connections for that token, destroys its rate limiter state, removes its sensor entities, and fires an `atm_token_revoked` event. All of this happens before the revoke response is returned.

Expired tokens are treated identically to revoked tokens at validation time.

### Admin API isolation

The admin API (`/api/atm/admin/`) requires a valid HA session and HA admin privileges. An ATM token cannot authenticate an admin request, even a pass-through token.

### Kill switch

When the kill switch is enabled at startup, ATM registers no proxy or MCP routes at all. The endpoints do not exist - there is nothing to respond with 503. The admin panel remains fully accessible. Disabling the kill switch re-registers all routes immediately without an HA restart.

### Request limits

- Request bodies exceeding 1 MB are rejected with 413 before any processing.
- SSE connections are limited to 5 per token. A sixth connection is rejected with 429.
- History queries are capped at a 7-day time range. Requests spanning more than 7 days are silently clamped to the most recent 7 days before hitting the recorder database. The actual queried range is always returned in `X-ATM-History-Start` and `X-ATM-History-End` response headers. Passing a `start_time` after `end_time` returns 400.
- Every response includes an `X-ATM-Request-ID` header with a UUID that matches the corresponding audit log entry.

---

## Telemetry and Sensors

ATM creates six HA sensor entities for each active token. For a token named `claude-code`:

| Entity | Description |
|---|---|
| `sensor.atm_claude_code_status` | `active`, `expired`, or `revoked` |
| `sensor.atm_claude_code_request_count` | Total requests made with this token |
| `sensor.atm_claude_code_denied_count` | Requests blocked by permission rules |
| `sensor.atm_claude_code_rate_limit_hits` | Times this token was rate limited |
| `sensor.atm_claude_code_last_access` | Timestamp of the most recent request |
| `sensor.atm_claude_code_expires_in` | Days until expiry, or `No expiry` if no expiry is set |

Sensors are removed automatically when a token is revoked. ATM sensors are blocked from all token access. External tools cannot read their own telemetry through ATM.

---

## Global Settings

| Setting | Default | Description |
|---|---|---|
| Kill switch | Off | When on, proxy and MCP routes are unregistered entirely |
| Disable all logging | Off | Suppresses all auditing |
| Log allowed requests | On | Record successful requests |
| Log denied requests | On | Record blocked requests and unsupported MCP method calls |
| Log rate-limited requests | On | Record rate-limited requests |
| Log entity names | On | Include entity IDs in audit entries |
| Log client IP | On | Include caller IP in audit entries |
| Notify on rate limit | Off | Create a HA notification when a token is rate limited |
| Audit log flush interval | 15 min | How often to snapshot the in-memory log to disk. Set to "Never" to disable persistence entirely. |
| Maximum log entries | 10,000 | Capacity of the in-memory buffer and the on-disk snapshot. Reducing this trims the oldest entries immediately. |

---

## Audit Log

ATM keeps a circular buffer of requests, queryable from the ATM panel or via the admin API. The default capacity is 10,000 entries, configurable in Global Settings.

Each entry records a unique request ID (matching the `X-ATM-Request-ID` response header), timestamp, token ID and name, HTTP method, resource path, outcome (`allowed`, `denied`, `not_found`, `rate_limited`, or `not_implemented`), and client IP.

`not_found` is recorded when an entity is genuinely absent from both HA state and the entity registry. From the caller's perspective it looks identical to `denied`, but the audit log distinguishes them so you can tell whether a token is hitting a missing entity or a permission wall.

`not_implemented` is recorded when an MCP client calls a method that ATM does not support (for example, `resources/templates/list`). This is a protocol-level gap, not a permission block, and does not increment the token's denied counter.

`invalid_request` is recorded when a request is structurally malformed and rejected before it reaches permission checks - for example, a template render call with a syntax error in the template body.

### Persistence

The audit log is stored in a separate HA storage file (`.storage/atm_audit.json`) and survives HA restarts.

The flush interval controls how often the in-memory buffer is snapshotted to disk. The default is every 15 minutes. ATM also flushes automatically on HA stop, integration reload, and integration unload. Set the interval to "Never" to keep the log in-memory only and disable all disk writes.

The storage file is included in HA full backups and in partial backups of the `.storage` directory.

---

## HA Events

| Event | Fired when |
|---|---|
| `atm_token_revoked` | A token is revoked |
| `atm_token_expired` | A token's expiry time passes and it is first accessed |
| `atm_token_rotated` | A token's raw value is rotated |
| `atm_rate_limited` | A token exceeds its rate limit (once per token per minute) |

Event data includes `token_id`, `token_name`, and `timestamp`. Revocation and rotation events also include `revoked_by` / `rotated_by` (the HA user ID of the admin who performed the action).

---

## Route Reference

### Admin API (requires HA session + admin role)

```
GET/POST   /api/atm/admin/tokens                              List or create tokens
GET/PATCH  /api/atm/admin/tokens/{id}                         Get or update a token
DELETE     /api/atm/admin/tokens/{id}                         Revoke a token
GET/PUT    /api/atm/admin/tokens/{id}/permissions             Read or replace permission tree
PATCH      /api/atm/admin/tokens/{id}/permissions/domains/{node}
PATCH      /api/atm/admin/tokens/{id}/permissions/devices/{node}
PATCH      /api/atm/admin/tokens/{id}/permissions/entities/{node}
GET        /api/atm/admin/tokens/{id}/resolve/{entity_id}     Explain effective permission (includes effective_hint)
POST       /api/atm/admin/tokens/{id}/rotate                  Generate a new raw token value (old value immediately invalid)
GET        /api/atm/admin/tokens/{id}/scope                   List all readable/writable entities
GET        /api/atm/admin/tokens/{id}/stats                   Request counters
GET        /api/atm/admin/tokens/{id}/audit                   Audit log for one token
GET        /api/atm/admin/tokens/archived                     List archived tokens
DELETE     /api/atm/admin/tokens/archived/{id}                Delete an archived record
GET        /api/atm/admin/entities                            Entity tree
GET        /api/atm/admin/info                                Integration version info
GET        /api/atm/admin/audit                               Global audit log
GET/PATCH  /api/atm/admin/settings                            Global settings
DELETE     /api/atm/admin/wipe                                Wipe all tokens and settings
```

### Proxy API (requires ATM token in Authorization: Bearer header)

```
GET        /api/atm/states                                    All accessible entity states
GET        /api/atm/states/{entity_id}                        One entity state
POST       /api/atm/services/{domain}/{service}               Call a service
GET        /api/atm/history/period/{timestamp}                State history (max 7-day range)
GET        /api/atm/statistics                                Long-term statistics
POST       /api/atm/template                                  Render a Jinja2 template
GET        /api/atm/config                                    HA configuration
GET        /api/atm/events                                    HA event bus listeners
GET        /api/atm/services                                  Accessible service list
GET        /api/atm/mcp                                       MCP SSE endpoint
POST       /api/atm/mcp                                       MCP Streamable HTTP endpoint
POST       /api/atm/mcp/messages?session_id={id}              MCP SSE message endpoint
GET        /api/atm/mcp/context                               Token context summary
```

---

## Issues and Feedback

Report issues at https://github.com/sfox38/atm/issues.
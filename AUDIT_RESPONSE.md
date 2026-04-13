# ATM Audit Response

This document records the disposition of every finding from the adversarial code analysis. Items marked FIXED have been addressed. Items marked CLOSED are disputed and explain why.

---

## High Criticality

### H-1 - Sensor values frozen at zero - FIXED
Confirmed and fixed. `_attr_should_poll = False` with no `async_write_ha_state()` calls meant HA read the sensor value once at entity creation and never again. Fixed by adding a `token_id_sensors` lookup dict to `ATMData` (keyed by token ID) and calling `sensor.async_write_ha_state()` from `update_token_counter()` in `helpers.py` after every counter increment. HA's `async_write_ha_state()` is synchronous and safe to call from a non-async context.

### H-2 - Multiple config entry creation - CLOSED (already fixed)
The finding is incorrect. `config_flow.py:17-18` already calls `await self.async_set_unique_id(DOMAIN)` followed by `self._abort_if_unique_id_configured()`. Attempting to create a second ATM entry raises `AbortFlow` and HA presents the user with "Already configured." The audit was written against an older version of the file.

### H-3 - SSE connection limit race condition - CLOSED (not a real race)
The finding does not apply to Python asyncio. asyncio is single-threaded and cooperative: a coroutine can only be preempted at an `await` point. Examining `mcp_view.py` lines 1034-1059, there are zero `await` calls between the connection count check and the `queue.add()` call - `rate_limiter.check()`, `update_last_used()`, and `_log()` are all synchronous. No concurrent coroutine can run between those two lines. The race described (two requests both reading count=4 and both proceeding) is a threading concern, not applicable to asyncio's event loop model.

### H-4 - `_tool_call_service` crashes on non-dict service_data - FIXED
Confirmed. `dict([1, 2, 3])` raises `TypeError` and the exception would propagate uncaught through `_call_tool` and `_dispatch_mcp`, dropping the SSE connection without a clean error response. Fixed with a one-line guard: `if not isinstance(service_data, dict): service_data = {}`.

### H-5 - filter_service_response depth limit passes unredacted entity IDs - FIXED
Confirmed. At depth > 10, the original code returned `response_data` unredacted regardless of type. Fixed by continuing to check strings for entity ID patterns even at depth > 10 - the depth limit now only stops recursing into dicts and lists (preventing unbounded traversal), not checking strings.

### H-6 - Template sandbox uses a blocklist - ACKNOWLEDGED, severity disputed
The finding is technically correct but the severity classification is wrong. Template execution requires `allow_template_render = true`, an explicitly granted capability that defaults to false and requires a conscious admin decision. The blocklist is defense-in-depth, not the primary security boundary; the primary boundary is the capability flag itself. The concern about new HA template functions being automatically accessible is real but manageable - this is reviewed when updating the minimum HA version requirement. The event loop blocking concern is valid but HA's template infrastructure already has its own timeout mechanisms. Classifying this as High implies it is exploitable without any misconfiguration, which is not the case. Acknowledged as a maintenance item; no code change in this pass.

### H-7 - Module-level `_panel_registered` global - CLOSED (moot)
The auditor's own description confirms the reload scenario works correctly: `remove_atm_panel` sets `_panel_registered = False` on unload, so the next `async_register_atm_panel` call re-registers correctly. The only scenario where this could cause issues is simultaneous duplicate config entries (H-2), which is already prevented by the single-instance enforcement in `config_flow.py`. With H-2 non-applicable, H-7 has no attack surface.

---

## Medium Criticality

### M-1 - Duplicate token auth logic - CLOSED (self-contradicting)
The audit itself contradicts its own finding: it states "Missing: the SSE handler does not log the rate_limited outcome via `fire_rate_limit_events`" then immediately corrects itself: "wait, it does at line 1042." The secondary concern - that `update_last_used` is called after logging, creating a TOCTOU window if expiry fires between those calls - is not exploitable. In asyncio, there are no `await` points between `update_last_used` and the final `_log` call, so no coroutine can preempt and run `archive_expired_token` between those two statements. The duplication is a code quality concern but not a bug or a vulnerability.

### M-2 - ATMServicesView misses domains with no live entity states - ACKNOWLEDGED
Valid practical concern. If all entities in a domain are unavailable, the domain disappears from the services list even if the token has a GREEN grant on it. Deferred - fixing this requires iterating the permission tree's domain grants rather than live states, which is a larger refactor. Tracked for a future pass.

### M-3 - Slug collision between hyphenated and underscored names - ACKNOWLEDGED
Valid. `my-token` and `my_token` produce the same slug, which causes sensor `unique_id` conflicts. The existing name regex forbids most collisions but not hyphen-vs-underscore. The SPEC already documents that slug uniqueness is enforced at token creation time. Deferred - requires adding a slug collision check at creation time that compares against the slugified form of all existing token names, not just the name verbatim.

### M-4 - server_info produces relative URLs when HA has no configured URL - FIXED
Confirmed. Using `hass.config.internal_url` can produce an empty string or None, resulting in relative paths in the `native_ha_mcp_endpoint` and `atm_context_endpoint` fields. Fixed by threading `base_url = str(request.url.origin())` from the request handler through `_dispatch_mcp` and into `_build_server_info`. The SSE messages endpoint and streamable HTTP POST endpoint both now pass the request origin URL, giving MCP clients an always-absolute, always-correct URL regardless of HA's URL configuration.

### M-5 - Dead mutation on popped token object - FIXED
Confirmed. `token.revoked = True` was called on a `TokenRecord` object that had already been popped from `self._tokens`. The mutation had no effect - the archived record was constructed independently from scratch below it with the `revoked` parameter. Removed the dead line.

### M-6 - Wipe epoch race with concurrent SSE sessions - CLOSED
The auditor correctly identifies this as inherent to the design and then notes that any proposed fix recreates the same window. The race window is microseconds during an admin-only wipe operation. The wipe is a destructive, manually triggered, admin-authenticated action - not an event that can be exploited by token holders. The existing comment in the code already documents this. No action taken.

### M-7 - Audit log query materializes entire buffer - CLOSED (premature optimization)
2.5 MB for a 10,000-entry buffer is not meaningful on any hardware that runs Home Assistant. The admin audit panel is not a hot path - it is accessed by a human administrator reviewing logs, not by a high-throughput client. Optimizing this before profiling shows it is a real bottleneck would add complexity for zero observable benefit.

### M-8 - Audit flush task can be cancelled mid-write - FIXED
Confirmed. If `audit_task.cancel()` fires while `audit.async_save()` is mid-execution inside `_audit_flush_loop`, `asyncio.CancelledError` propagates through the write. Fixed by wrapping the entire loop body in `try/except asyncio.CancelledError: return`. The `_on_stop` handler still calls `await audit.async_save()` independently after cancelling the task, so the final flush on shutdown is clean and unaffected.

### M-9 - Template blocklist duplicated verbatim in two files - FIXED
Confirmed. The identical 20-entry blocklist dict existed in both `proxy_view.py` and `mcp_view.py`. Fixed by extracting it to `template_blocklist_vars()` in `policy_engine.py` and replacing both inline copies with `**template_blocklist_vars()`. Any future security patch to the blocklist now has a single location.

### M-10 - require_admin returns 403 for unauthenticated callers - CLOSED
Not a real issue in practice. Admin views set `requires_auth = True` at the `HomeAssistantView` class level. HA's HTTP middleware intercepts unauthenticated requests before they reach the view handler, so `KEY_HASS_USER` cannot be `None` inside `require_admin`. The decorator only fires for users who have already passed HA's session authentication; its job is to additionally check `is_admin`. Returning 403 for non-admin authenticated users is correct. An unauthenticated request never reaches the decorator.

### M-11 - force_reload entity tree has no rate limit - CLOSED
`GET /api/atm/admin/entities?force_reload=1` is an admin-authenticated endpoint. HA admins already have full access to the HA instance including direct database queries and configuration changes. An admin deliberately hammering this endpoint is a self-inflicted denial of service on their own HA installation - not a security issue ATM should defend against. Adding a rate limit here would impose friction on legitimate admin tooling without providing any meaningful protection.

---

## Low Criticality

### L-1 - Empty translations/en.json - ACKNOWLEDGED
Valid. Deferred - translation strings are a polish item. HA falls back to key names, which are readable for a single-language integration at this stage.

### L-2 - Missing PARALLEL_UPDATES - FIXED
Added `PARALLEL_UPDATES = 0` to `sensor.py`. For poll-disabled sensors this constant has no practical effect but satisfies HA's quality scale requirements.

### L-3 - Missing _attr_icon - ACKNOWLEDGED
Valid cosmetic issue. Deferred - icon selection requires a design decision for each sensor type; tracked as a polish item.

### L-4 - Raw "d" instead of UnitOfTime.DAYS - FIXED
Fixed. Import added: `from homeassistant.const import UnitOfTime`. Native unit changed from `"d"` to `UnitOfTime.DAYS`.

### L-5 - AUDIT_FLUSH_INTERVAL_DEFAULT is dead code - FIXED
Confirmed. `AUDIT_FLUSH_INTERVAL_DEFAULT = 15` was defined in `const.py` but the `GlobalSettings` dataclass hardcodes the default directly. Removed the unused constant.

### L-6 - Device node ID validation accepts arbitrary strings - ACKNOWLEDGED
Valid. Device IDs in HA are UUIDs; accepting arbitrary strings allows permission nodes for non-existent devices to be stored silently. The practical impact is low - the grant is ineffective since no entity's `device_id` will match the bogus string. Deferred - adding UUID format validation is straightforward but requires a separate pass.

### L-7 - AuditLog.query does not validate outcome parameter - ACKNOWLEDGED
Valid. Providing an unknown outcome value returns an empty list rather than a 400 error, which is confusing to admin clients. Deferred.

### L-8 - No coordination between in-flight requests and unload - CLOSED
This is inherent to HA's integration unload model. HA does not provide a mechanism to drain in-flight requests before unloading an integration. All HA integrations that serve HTTP requests share this characteristic. The documented behavior is that HA's own HTTP server handles connection management. ATM cannot and should not attempt to reimplement request draining.

### L-9 - Stats endpoint may show expired for still-valid token - ACKNOWLEDGED
Valid edge case. There is a window between when `token.is_expired()` returns true and when the background task archives the token. The stats endpoint reporting "expired" during this window while the token still accepts requests is a cosmetic inconsistency. Deferred.

### L-10 - Inconsistent truthiness semantics on history query params - ACKNOWLEDGED
Valid. `significant_changes_only=false` (the string "false") is treated as truthy because the check is `!= "0"` rather than a proper boolean parse. Deferred - fixing this requires a small dedicated boolean-from-string utility.

### L-11 - Admin imports private function from MCP view - FIXED
Confirmed architectural smell. `_get_effective_hint` was defined in `mcp_view.py` (indicated by its `_` prefix as a private function) and imported into `admin_view.py`. Fixed by moving `get_effective_hint` (now public) to `policy_engine.py` where it belongs alongside the other permission resolution logic. Both `admin_view.py` and `mcp_view.py` now import it from `policy_engine`. The cross-module dependency between admin and MCP layers is eliminated.

### L-12 - helpers.py re-exports token_name_slug - ACKNOWLEDGED
Valid minor indirection. `sensor.py` imports `token_name_slug` from `helpers.py` but the function is defined in `token_store.py`. The re-export is invisible but misleading. Deferred as a trivial cleanup - the import path in `sensor.py` can be updated to import directly from `token_store.py` in a future cleanup pass.

### L-13 - No upper bound on rate limit values - ACKNOWLEDGED
Valid admin-configuration concern. Setting `rate_limit_requests = 999999` effectively disables rate limiting while leaving headers with meaningless values. Deferred - adding a reasonable upper bound (e.g. 10,000 requests/min) is a one-line validation addition in the PATCH handler.

# Using External MCP Servers with ATM

ATM is a security layer, not a replacement for third-party Home Assistant MCP servers. A third-party server may offer dozens of specialized tools - automation editing, dashboard management, system administration - that ATM does not implement. ATM's role is to control which credentials those tools run under and to give you audit, revocation, and rate limiting on top.

This document explains how to route external MCP servers through ATM, and when that is and is not the right approach.

---

## The core idea

Most third-party HA MCP servers accept a credential - typically a LLAT - and use it to talk to your Home Assistant instance. ATM lets you substitute an ATM pass-through token for that LLAT. The external server gets the same entity access it would have with a LLAT, but you gain:

- **Instant revocation.** One click in the ATM panel terminates access immediately.
- **Expiry.** Set a 24-hour or 7-day token for a specific task and it expires automatically.
- **Audit log.** Every request made through the token is recorded with timestamp, entity, and client IP.
- **Rate limiting.** Prevent runaway tool calls from hammering your HA instance.
- **Sensitive attribute scrubbing.** Camera tokens, stream URLs, and other sensitive attributes are stripped from every response.

---

## When to use a pass-through token

Use a pass-through ATM token with an external MCP server when:

- You want the external server's full tool set without restriction.
- You want revocability and audit logging that a raw LLAT cannot provide.
- You are using the server for a short-lived task and want automatic expiry.

Do not use pass-through when:

- You want to limit which entities the external server can see or control. Pass-through bypasses the permission tree entirely. Use a scoped token instead.
- The external server is running as an untrusted process or is hosted outside your network. For those cases, a scoped token with an explicit permission tree is the safer choice.

---

## Setting up a pass-through token

1. Open the ATM sidebar panel and click **Create Token**.
2. Give it a descriptive name (e.g. `ha-mcp-passthrough`).
3. Toggle **Pass-through mode** on and confirm the warning.
4. Set an expiry date if the token is for a specific task.
5. Copy the raw token value. It is shown once.

This token can now be used anywhere a LLAT is accepted, provided the external server passes it as an HTTP `Authorization: Bearer` header.

---

## Connecting an external MCP server

### Servers that accept a Bearer token via HTTP

If the external server makes HTTP requests to your HA instance and accepts a configurable credential, simply replace the LLAT with your ATM token. No other configuration change is needed.

```bash
# Before (using LLAT)
HOMEASSISTANT_TOKEN="eyJhbGci..."

# After (using ATM pass-through token)
HOMEASSISTANT_TOKEN="atm_your_pass_through_token_here"
```

The ATM token starts with `atm_` and is 68 characters. It is accepted in the same `Authorization: Bearer` header position as a LLAT.

### Servers that connect via the native HA MCP endpoint

Some servers connect to HA's native MCP endpoint (`/api/mcp`) rather than the REST API. These cannot be directly routed through ATM's MCP endpoint, but you can still use an ATM pass-through token as the credential if the server accepts a configurable token.

### Servers launched as local processes (stdio transport)

Some MCP servers run as a local subprocess and receive credentials via environment variables rather than HTTP headers. In these cases you can still use an ATM pass-through token:

```json
{
  "mcpServers": {
    "ha-full": {
      "command": "uvx",
      "args": ["some-ha-mcp-server"],
      "env": {
        "HOMEASSISTANT_TOKEN": "atm_your_pass_through_token_here",
        "HOMEASSISTANT_URL": "http://homeassistant.local:8123"
      }
    }
  }
}
```

The external server will use the ATM token for all its HA API calls. ATM will log and rate-limit those calls as normal.

### Running ATM alongside an external server

ATM and an external MCP server can coexist in the same client configuration. The LLM sees both tool sets and can choose which to use:

```json
{
  "mcpServers": {
    "ha-full": {
      "command": "uvx",
      "args": ["some-ha-mcp-server"],
      "env": {
        "HOMEASSISTANT_TOKEN": "atm_your_pass_through_token_here"
      }
    },
    "ha-scoped": {
      "url": "http://homeassistant.local:8123/api/atm/mcp",
      "headers": {
        "Authorization": "Bearer atm_your_scoped_token_here"
      }
    }
  }
}
```

In this setup, the full-access server handles complex operations like automation editing, while the scoped ATM endpoint handles everyday entity queries with tighter permissions.

---

## Limitations

**Pass-through does not scope entity access.** The token holder can read and control any entity in HA except the `atm` domain itself. If you need entity-level restrictions, use a scoped ATM token and the ATM MCP endpoint directly.

**`homeassistant/restart` and `homeassistant/stop` require an explicit flag.** Even pass-through tokens cannot call these services unless `allow_restart` is enabled on the token. This is a deliberate exception to pass-through's wide access.

**Sensitive attributes are always scrubbed.** Even through a pass-through token, the fields `access_token`, `entity_picture`, `stream_url`, and `still_image_url` are stripped from all state responses. If an external server depends on these fields, it will need to access the native HA API directly.

**The audit log records ATM-level requests only.** If an external server batches multiple HA operations into a single tool call, the audit log will show one entry for that call, not individual entity accesses within it.

---

## Getting a context summary for your LLM

After connecting, call the context endpoint to get a plain-text summary of what the token can access. This is useful as a system prompt addition:

```bash
curl -H "Authorization: Bearer atm_your_token" \
  http://homeassistant.local:8123/api/atm/mcp/context
```

For JSON format:

```bash
curl -H "Authorization: Bearer atm_your_token" \
  "http://homeassistant.local:8123/api/atm/mcp/context?format=json"
```

Paste the plain text output into your system prompt. It tells the LLM exactly which entities it can access and which capability flags are enabled, preventing it from wasting tokens on calls it will be denied.
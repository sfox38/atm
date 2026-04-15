import React, { useState } from "react";
import type { TokenRecord, PatchTokenBody } from "../types";
import { api } from "../api";

interface Props {
  token: TokenRecord;
  onUpdate: (updated: TokenRecord) => void;
}

export function PassThroughNotice({ token, onUpdate }: Props) {
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function convertToScoped() {
    setSaving(true);
    setError(null);
    try {
      const body: PatchTokenBody = { pass_through: false };
      const updated = await api.patchToken(token.id, body);
      onUpdate(updated);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to convert token.");
    } finally {
      setSaving(false);
      setConfirming(false);
    }
  }

  return (
    <div>
      <div className="pass-through-header-banner">
        <p>
          <strong style={{ color: "var(--warning-color, #ff9800)" }}>Pass Through token.</strong> This token bypasses the permission tree and has unrestricted access to Home Assistant entities and services. Sensitive attributes are still scrubbed, and the five exempt flags below still apply. The ATM domain is always blocked.
        </p>
        <p style={{ marginTop: 8 }}>
          The flags for restarting Home Assistant, controlling physical devices (locks and alarms), writing automations, writing scripts, and reading logs must still be individually enabled below.
        </p>
        <p style={{ marginTop: 8 }}>
          This token works only with HTTP-based MCP clients (such as Claude Code with <code>--transport http</code>). It cannot be used with stdio-based MCP server setups.
        </p>
      </div>

      {error && <div className="banner banner-error">{error}</div>}

      {!confirming ? (
        <button
          className="btn btn-outline"
          onClick={() => setConfirming(true)}
        >
          Convert to Scoped
        </button>
      ) : (
        <div className="card" style={{ margin: 0 }}>
          <p style={{ margin: "0 0 12px" }}>
            Converting to scoped will immediately apply the stored permission tree. The permission tree will be empty unless grants were previously configured, meaning the token will have no access until you add grants.
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              className="btn btn-primary"
              onClick={convertToScoped}
              disabled={saving}
            >
              {saving ? "Converting..." : "Confirm Convert"}
            </button>
            <button className="btn btn-text" onClick={() => setConfirming(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

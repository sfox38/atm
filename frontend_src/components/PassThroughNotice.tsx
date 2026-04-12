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
          <strong style={{ color: "var(--warning-color, #ff9800)" }}>Full Access token.</strong> This token has unrestricted access to all Home Assistant entities and services. No entity scoping or capability restrictions apply. Only revocation, TTL, rate limiting, and audit logging are active.
        </p>
        <p style={{ marginTop: 8 }}>
          The <strong>allow restart/stop</strong> dual-gate still applies and is configurable in the left column.
        </p>
        <p style={{ marginTop: 8 }}>
          Stdio limitation: this token cannot be used to replace a LLAT in stdio-based MCP server configurations. It works only with HTTP-based MCP clients that present the token as an Authorization: Bearer header.
        </p>
        <p style={{ marginTop: 8, fontSize: 12, color: "var(--secondary-text-color, #9e9e9e)" }}>
          Not compatible with stdio-based MCP server setups.
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

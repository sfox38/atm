import React, { useState, useEffect } from "react";
import type { TokenRecord, PatchTokenBody } from "../types";
import { api } from "../api";

interface Props {
  token: TokenRecord;
  onUpdate: (updated: TokenRecord) => void;
}

export function RateLimitConfig({ token, onUpdate }: Props) {
  const [requests, setRequests] = useState(String(token.rate_limit_requests));
  const [burst, setBurst] = useState(String(token.rate_limit_burst));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setRequests(String(token.rate_limit_requests));
    setBurst(String(token.rate_limit_burst));
    setDirty(false);
  }, [token.rate_limit_requests, token.rate_limit_burst]);

  const requestsNum = parseInt(requests, 10);
  const burstDisabled = isNaN(requestsNum) || requestsNum === 0;

  async function save() {
    const reqNum = parseInt(requests, 10);
    const burstNum = burstDisabled ? 0 : parseInt(burst, 10);
    if (isNaN(reqNum) || reqNum < 0 || isNaN(burstNum) || burstNum < 0) {
      setError("Values must be non-negative integers.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const body: PatchTokenBody = {
        rate_limit_requests: reqNum,
        rate_limit_burst: burstNum,
      };
      const updated = await api.patchToken(token.id, body);
      onUpdate(updated);
      setDirty(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      {error && <div className="banner banner-error" style={{ marginBottom: 8 }}>{error}</div>}
      <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
        <div className="field" style={{ margin: 0, flex: 1 }}>
          <label>Requests per minute (0 = disabled)</label>
          <input
            className="input"
            type="number"
            min={0}
            value={requests}
            onChange={(e) => { setRequests(e.target.value); setDirty(true); }}
          />
        </div>
        <div className="field" style={{ margin: 0, flex: 1 }}>
          <label>Burst per second</label>
          <input
            className="input"
            type="number"
            min={0}
            value={burstDisabled ? "0" : burst}
            disabled={burstDisabled}
            onChange={(e) => { setBurst(e.target.value); setDirty(true); }}
          />
        </div>
        <button
          className="btn btn-primary btn-sm"
          onClick={save}
          disabled={saving || !dirty}
          style={{ marginBottom: 12 }}
        >
          {saving ? "Saving..." : "Save"}
        </button>
      </div>
      {requestsNum === 0 && (
        <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--secondary-text-color, #9e9e9e)" }}>
          Rate limiting is disabled for this token.
        </p>
      )}
    </div>
  );
}

import React, { useState, useEffect, useRef } from "react";
import type { TokenRecord, PatchTokenBody } from "../types";
import { api } from "../api";

interface Props {
  token: TokenRecord;
  onUpdate: (updated: TokenRecord) => void;
}

export function RateLimitConfig({ token, onUpdate }: Props) {
  const [requests, setRequests] = useState(String(token.rate_limit_requests));
  const [burst, setBurst] = useState(String(token.rate_limit_burst));
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setRequests(String(token.rate_limit_requests));
    setBurst(String(token.rate_limit_burst));
  }, [token.rate_limit_requests, token.rate_limit_burst]);

  const requestsNum = parseInt(requests, 10);
  const burstDisabled = isNaN(requestsNum) || requestsNum === 0;

  async function save(reqStr: string, burstStr: string) {
    const reqNum = parseInt(reqStr, 10);
    const burstNum = burstDisabled ? 0 : parseInt(burstStr, 10);
    if (isNaN(reqNum) || reqNum < 0 || isNaN(burstNum) || burstNum < 0) {
      setError("Values must be non-negative integers.");
      return;
    }
    setError(null);
    try {
      const body: PatchTokenBody = {
        rate_limit_requests: reqNum,
        rate_limit_burst: burstNum,
      };
      const updated = await api.patchToken(token.id, body);
      onUpdate(updated);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed.");
    }
  }

  function scheduleAutoSave(reqStr: string, burstStr: string) {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => save(reqStr, burstStr), 800);
  }

  function handleBlur(reqStr: string, burstStr: string) {
    if (timerRef.current) clearTimeout(timerRef.current);
    save(reqStr, burstStr);
  }

  return (
    <div>
      {error && <div className="banner banner-error mb-8">{error}</div>}
      <div className="rate-limit-row">
        <div className="field">
          <label>Requests per minute (0 = disabled)</label>
          <input
            className="input"
            type="number"
            min={0}
            value={requests}
            onChange={(e) => { setRequests(e.target.value); scheduleAutoSave(e.target.value, burst); }}
            onBlur={(e) => handleBlur(e.target.value, burst)}
          />
        </div>
        <div className="field">
          <label>Burst per second</label>
          <input
            className="input"
            type="number"
            min={0}
            value={burstDisabled ? "0" : burst}
            disabled={burstDisabled}
            onChange={(e) => { setBurst(e.target.value); scheduleAutoSave(requests, e.target.value); }}
            onBlur={(e) => handleBlur(requests, e.target.value)}
          />
        </div>
      </div>
      {requestsNum === 0 && (
        <p className="rate-limit-disabled-text">
          Rate limiting is disabled for this token.
        </p>
      )}
    </div>
  );
}

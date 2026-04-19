import React, { useState, useEffect, useCallback, useRef } from "react";
import type { ResolveResult } from "../types";
import { api } from "../api";

interface Props {
  tokenId: string;
  externalEntityId?: string;
  triggerVersion?: number;
}

const EFFECTIVE_CLASS: Record<string, string> = {
  WRITE: "state-GREEN",
  READ: "state-YELLOW",
  DENY: "state-RED",
  NO_ACCESS: "state-GREY",
  NOT_FOUND: "state-GREY",
};

export function PermissionSimulator({ tokenId, externalEntityId, triggerVersion }: Props) {
  const [entityInput, setEntityInput] = useState(externalEntityId ?? "");
  const [result, setResult] = useState<ResolveResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const entityInputRef = useRef(entityInput);
  entityInputRef.current = entityInput;
  const externalUpdateRef = useRef(false);
  const genRef = useRef(0);

  const simulate = useCallback(async (eid: string) => {
    if (!eid.trim()) return;
    const gen = ++genRef.current;
    setLoading(true);
    setError(null);
    try {
      const data = await api.resolve(tokenId, eid.trim());
      if (gen !== genRef.current) return;
      setResult(data);
    } catch (e: unknown) {
      if (gen !== genRef.current) return;
      setError(e instanceof Error ? e.message : "Simulation failed.");
      setResult(null);
    } finally {
      if (gen !== genRef.current) return;
      setLoading(false);
    }
  }, [tokenId]);

  // External entity click: update input and simulate immediately, suppress debounce
  useEffect(() => {
    if (externalEntityId) {
      externalUpdateRef.current = true;
      setEntityInput(externalEntityId);
      simulate(externalEntityId);
    }
  }, [externalEntityId, simulate]);

  // Permissions changed: re-simulate current entity
  useEffect(() => {
    if (triggerVersion && triggerVersion > 0 && entityInputRef.current.trim()) {
      simulate(entityInputRef.current.trim());
    }
  }, [triggerVersion, simulate]);

  // Manual typing: debounce 600ms (skip if input was set externally)
  useEffect(() => {
    if (!entityInput.trim()) return;
    if (externalUpdateRef.current) {
      externalUpdateRef.current = false;
      return;
    }
    const timer = setTimeout(() => simulate(entityInput), 600);
    return () => clearTimeout(timer);
  }, [entityInput, simulate]);

  return (
    <div>
      <input
        className="input"
        placeholder="entity_id (e.g. light.kitchen)"
        value={entityInput}
        onChange={(e) => setEntityInput(e.target.value)}
      />
      {loading && !result && <div className="sim-loading">Simulating...</div>}
      {error && <div className="banner banner-error mt-6">{error}</div>}
      {result && (
        <div className="sim-path">
          {result.resolution_path.map((step, i) => (
            <div key={i} className="sim-step">
              <span className="sim-resolution-level">{step.level}</span>
              {" -> "}
              <span className={`state-${step.state}`}>
                {step.state}
              </span>
            </div>
          ))}
          <div className="sim-result">
            {"Result: "}
            <span className={EFFECTIVE_CLASS[result.effective] ?? "state-GREY"}>
              {result.effective}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

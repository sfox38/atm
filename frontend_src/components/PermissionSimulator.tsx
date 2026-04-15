import React, { useState, useEffect, useCallback, useRef } from "react";
import type { ResolveResult } from "../types";
import { api } from "../api";

interface Props {
  tokenId: string;
  externalEntityId?: string;
  triggerVersion?: number;
}

export function PermissionSimulator({ tokenId, externalEntityId, triggerVersion }: Props) {
  const [entityInput, setEntityInput] = useState(externalEntityId ?? "");
  const [result, setResult] = useState<ResolveResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const entityInputRef = useRef(entityInput);
  entityInputRef.current = entityInput;
  const externalUpdateRef = useRef(false);

  const simulate = useCallback(async (eid: string) => {
    if (!eid.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.resolve(tokenId, eid.trim());
      setResult(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Simulation failed.");
      setResult(null);
    } finally {
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

  const effectiveColor: Record<string, string> = {
    WRITE: "var(--success-color, #4caf50)",
    READ: "var(--warning-color, #ff9800)",
    DENY: "var(--error-color, #f44336)",
    NO_ACCESS: "var(--secondary-text-color, #9e9e9e)",
    NOT_FOUND: "var(--secondary-text-color, #9e9e9e)",
  };

  return (
    <div>
      <input
        className="input"
        placeholder="entity_id (e.g. light.kitchen)"
        value={entityInput}
        onChange={(e) => setEntityInput(e.target.value)}
        style={{ width: "100%", boxSizing: "border-box" }}
      />
      {loading && !result && <div style={{ fontSize: 12, color: "var(--secondary-text-color, #9e9e9e)", marginTop: 6 }}>Simulating...</div>}
      {error && <div className="banner banner-error" style={{ marginTop: 6 }}>{error}</div>}
      {result && (
        <div className="sim-path">
          {result.resolution_path.map((step, i) => (
            <div key={i} className="sim-step">
              <span style={{ color: "var(--secondary-text-color, #9e9e9e)" }}>{step.level}</span>
              {" -> "}
              <span
                style={{
                  color:
                    step.state === "GREEN" ? "var(--success-color, #4caf50)"
                    : step.state === "YELLOW" ? "var(--warning-color, #ff9800)"
                    : step.state === "RED" ? "var(--error-color, #f44336)"
                    : "var(--secondary-text-color, #9e9e9e)",
                }}
              >
                {step.state}
              </span>
            </div>
          ))}
          <div style={{ marginTop: 8, fontWeight: 500 }}>
            {"Result: "}
            <span style={{ color: effectiveColor[result.effective] ?? "#9e9e9e" }}>
              {result.effective}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

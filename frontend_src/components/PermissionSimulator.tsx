import React, { useState } from "react";
import type { ResolveResult } from "../types";
import { api } from "../api";

interface Props {
  tokenId: string;
}

export function PermissionSimulator({ tokenId }: Props) {
  const [entityInput, setEntityInput] = useState("");
  const [result, setResult] = useState<ResolveResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function simulate() {
    const eid = entityInput.trim();
    if (!eid) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await api.resolve(tokenId, eid);
      setResult(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Simulation failed.");
    } finally {
      setLoading(false);
    }
  }

  const effectiveColor: Record<string, string> = {
    WRITE: "var(--success-color, #4caf50)",
    READ: "var(--warning-color, #ff9800)",
    DENY: "var(--error-color, #f44336)",
    NO_ACCESS: "var(--secondary-text-color, #9e9e9e)",
    NOT_FOUND: "var(--secondary-text-color, #9e9e9e)",
  };

  return (
    <div>
      <div className="filter-row">
        <input
          className="input"
          placeholder="entity_id (e.g. light.kitchen)"
          value={entityInput}
          onChange={(e) => setEntityInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") simulate(); }}
        />
        <button className="btn btn-outline btn-sm" onClick={simulate} disabled={loading || !entityInput.trim()}>
          {loading ? "..." : "Simulate"}
        </button>
      </div>
      {error && <div className="banner banner-error">{error}</div>}
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

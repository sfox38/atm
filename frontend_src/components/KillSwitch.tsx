import React from "react";
import type { GlobalSettings } from "../types";

interface Props {
  settings: GlobalSettings;
  onToggle: (value: boolean) => void;
  saving: boolean;
}

export function KillSwitch({ settings, onToggle, saving }: Props) {
  const active = settings.kill_switch;

  return (
    <div className={active ? "kill-switch-active" : ""}>
      <div className="toggle-row" style={{ border: "none", padding: 0 }}>
        <div className="toggle-label">
          <span style={{ fontWeight: 500, color: active ? "var(--error-color, #f44336)" : undefined }}>
            {active ? "Kill switch ACTIVE - All ATM endpoints are disabled" : "Disable all ATM endpoints"}
          </span>
          <small>
            {active
              ? "Open SSE connections have been terminated. Re-enabling will re-register all ATM routes immediately, without an HA restart."
              : "When enabled, all ATM proxy and MCP endpoints are immediately disabled. The admin panel remains accessible."}
          </small>
        </div>
        <label style={{ display: "flex", alignItems: "center", cursor: saving ? "not-allowed" : "pointer" }}>
          <input
            type="checkbox"
            checked={active}
            disabled={saving}
            onChange={(e) => onToggle(e.target.checked)}
            style={{ width: 18, height: 18, accentColor: "var(--error-color, #f44336)", cursor: "inherit" }}
          />
        </label>
      </div>
    </div>
  );
}

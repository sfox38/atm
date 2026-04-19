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
      <div className="toggle-row toggle-row-plain">
        <div className="toggle-label">
          <span className={active ? "kill-switch-label-active" : "kill-switch-label"}>
            {active ? "Kill switch ACTIVE - All ATM endpoints are disabled" : "Disable all ATM endpoints"}
          </span>
          <small>
            {active
              ? "Open SSE connections have been terminated. Re-enabling will re-register all ATM routes immediately, without an HA restart."
              : "When enabled, all ATM proxy and MCP endpoints are immediately disabled. The admin panel remains accessible."}
          </small>
        </div>
        <label className={`toggle-checkbox-label${saving ? " disabled" : ""}`}>
          <input
            type="checkbox"
            checked={active}
            disabled={saving}
            onChange={(e) => onToggle(e.target.checked)}
            className="toggle-checkbox-error"
          />
        </label>
      </div>
    </div>
  );
}

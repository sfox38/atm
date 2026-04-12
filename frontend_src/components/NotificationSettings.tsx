import React from "react";
import type { GlobalSettings } from "../types";

interface Props {
  settings: GlobalSettings;
  onToggle: (key: keyof GlobalSettings, value: boolean) => void;
  saving: boolean;
}

export function NotificationSettings({ settings, onToggle, saving }: Props) {
  return (
    <div>
      <div className="toggle-row">
        <div className="toggle-label">
          <span>Notify on rate limit breach</span>
          <small>
            Sends a HA persistent notification when any token hits its rate limit. Throttled to one notification per token per minute.
          </small>
        </div>
        <label style={{ display: "flex", alignItems: "center", cursor: saving ? "not-allowed" : "pointer" }}>
          <input
            type="checkbox"
            checked={settings.notify_on_rate_limit}
            disabled={saving}
            onChange={(e) => onToggle("notify_on_rate_limit", e.target.checked)}
            style={{ width: 18, height: 18, accentColor: "var(--primary-color, #03a9f4)", cursor: "inherit" }}
          />
        </label>
      </div>
    </div>
  );
}
